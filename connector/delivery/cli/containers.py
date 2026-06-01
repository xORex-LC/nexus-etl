"""
Назначение:
    Composition Root для CLI-приложения: DI-контейнеры и AppContainer.

    Модуль содержит иерархию DI-контейнеров для управления lifecycle
    инфраструктурных ресурсов (SQLite engines, vault services, cache gateway,
    HTTP target runtime) и сборки transform pipeline (PipelineContainer).

    AppContainer — единый CR, создаётся в run_with_report() / run_without_report().
    Command handlers получают зависимости через ctx.container.*.

Граница ответственности:
    - SqliteContainer: lifecycle трёх SQLite engines (cache, vault, identity).
    - VaultContainer: vault-сервисы (cipher, read/write/retention) поверх vault_engine.
    - CacheContainer: cache gateway (Resource) + role-based порты (Singleton).
    - TargetContainer: lifecycle DefaultTargetRuntime (HTTP-клиент + gateway).
    - DictionaryContainer: lifecycle dictionary runtime v1 (optional DSL+CSV+Polars backend).
    - PipelineContainer: lazy transform/planning stages + orchestrators (DEC-004).
    - AppContainer: монтирует все sub-containers; единственный CR.
    - _init_container_for_requirements(): условная инициализация ресурсов по Requirements.
    - build_diagnostics_catalog(), build_dataset_spec(): stateless утилиты.
    - Никакой доменной логики — только сборка графа зависимостей.

Зависимости:
    Единственный модуль вне infra/, которому разрешено импортировать
    connector.infra.secrets.*, connector.infra.cache.*, connector.infra.sqlite.*
    для сборки DI-графа.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

from dependency_injector import containers, providers

from connector.config.models import ApiConfig, AppConfig, DatasetConfig
from connector.config.projections import (
    to_cache_db_config,
    to_dataset_registry_path,
    to_identity_db_config,
    to_resolver_settings,
    to_runtime_path_overrides,
    to_vault_management_settings,
    to_vault_db_config,
)
from connector.common.runtime_paths import detect_runtime_paths
from connector.domain.transform.matcher.match_deps import MatchBatchSettings, MatchScopeService
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.domain.diagnostics import build_catalog
from connector.domain.ports.cache.roles import (
    EnrichLookupPort,
    MatchRuntimePort,
    ResolveRuntimePort,
)
from connector.domain.ports.topology import TopologyProviderPort
from connector.domain.ports.topology import TopologyRuntimeRequirements
from connector.domain.ports.secrets.provider import SecretProviderProtocol, SecretStoreProtocol
from connector.domain.ports.transform.dictionaries import DictionaryProviderPort
from connector.domain.secrets.secret_locator_service import SecretLocatorService
from connector.domain.secrets.vault_retention_service import VaultRetentionService
from connector.domain.secrets.secret_vault_read_service import SecretVaultReadService
from connector.domain.secrets.secret_vault_write_service import SecretVaultWriteService
from connector.domain.secrets.vault_startup_guard import VaultStartupGuard
from connector.domain.transform.context import PipelineMetadata, StageExecutionContext
from connector.domain.transform.providers import ProviderGateway
from connector.domain.transform_dsl.compilers.resolve import ResolveDsl
from connector.domain.transform.pipeline_run_context import PipelineRunContext
from connector.domain.transform.matcher.dedup_store import LocalSourceDedupStore
from connector.domain.transform.matcher.match_engine import MatchEngine
from connector.domain.transform.resolver.batch_index_service import InMemoryBatchIndexService
from connector.domain.transform.resolver.pending_codec import PendingCodecAdapter
from connector.domain.transform.resolver.pending_expiry_service import PendingExpiryService
from connector.domain.transform.resolver.resolve_engine import ResolveEngine
from connector.domain.transform.stages.stages import MatchStage, ResolveContextStage, ResolveStage
from connector.datasets.registry import get_spec, resolve_dataset_name, validate_registry
from connector.datasets.spec import DatasetSpec
from connector.delivery.cli.stages import PIPELINE_CHECKPOINTS, StageName
from connector.delivery.cli.stages import PipelineComposer
from connector.delivery.cli.stages import build_stage_factory
from connector.delivery.cli.dictionaries_container import DictionaryContainer
from connector.delivery.pipelines.planning_pipeline import PlanningPipeline
from connector.delivery.pipelines.planning_pipeline_hooks import PlanningPipelineHooks
from connector.domain.transform_dsl import (
    load_enrich_build_options_for_dataset,
    load_map_build_options_for_dataset,
    load_match_build_options_for_dataset,
    load_normalize_build_options_for_dataset,
    load_resolve_build_options_for_dataset,
)
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.cache.dsl_runtime import load_cache_dsl_runtime
from connector.infra.cache.roles import SqliteCacheRolePorts, build_sqlite_cache_role_ports
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.identity.sqlite.schema import ensure_identity_schema
from connector.infra.secrets import (
    FernetEnvelopeCipher,
    UnsealedVaultKeyProvider,
    VaultAdminPasswordGate,
    VaultUnsealService,
)
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.secrets.sqlite.schema import ensure_vault_schema
from connector.infra.sqlite.engine import SqliteEngine, open_sqlite
from connector.infra.target.core.factory import (
    TargetRuntimeBuildResult,
    build_target_runtime_with_info,
)
from connector.usecases.management.vault import (
    VaultKeyManagementUseCase,
    VaultStartupGuardPostVerifier,
)

if TYPE_CHECKING:
    from connector.delivery.cli.requirements import Requirements

# ──────────────────────────────────────────────────────────────────────────────
# Path helpers
# ──────────────────────────────────────────────────────────────────────────────


def _runtime_paths_for(app_config: AppConfig):
    return detect_runtime_paths(overrides=to_runtime_path_overrides(app_config))


def _resolve_sqlite_file_path(
    *,
    app_config: AppConfig,
    override: str | None,
    default_name: str,
) -> str:
    runtime_paths = _runtime_paths_for(app_config)
    if override:
        return str((runtime_paths.root / override).resolve())
    return str(runtime_paths.resolve_cache_db_file(default_name))


def _cache_db_path(app_config: AppConfig) -> str:
    return _resolve_sqlite_file_path(
        app_config=app_config,
        override=app_config.sqlite.cache_db_path,
        default_name="ankey_cache.sqlite3",
    )


def _vault_db_path(app_config: AppConfig) -> str:
    return _resolve_sqlite_file_path(
        app_config=app_config,
        override=app_config.sqlite.vault_db_path,
        default_name="ankey_vault.sqlite3",
    )


def _identity_db_path(app_config: AppConfig) -> str:
    return _resolve_sqlite_file_path(
        app_config=app_config,
        override=app_config.sqlite.identity_db_path,
        default_name="identity.sqlite3",
    )


# ──────────────────────────────────────────────────────────────────────────────
# DI-контейнер: управление lifecycle SqliteEngine
# ──────────────────────────────────────────────────────────────────────────────


def _make_cache_engine(app_config: AppConfig, cache_dir: str) -> SqliteEngine:
    _ = cache_dir
    return open_sqlite(to_cache_db_config(app_config), _cache_db_path(app_config))


def _make_vault_engine(app_config: AppConfig, cache_dir: str) -> SqliteEngine:
    _ = cache_dir
    return open_sqlite(to_vault_db_config(app_config), _vault_db_path(app_config))


def _make_identity_engine(app_config: AppConfig, cache_dir: str) -> SqliteEngine:
    _ = cache_dir
    return open_sqlite(to_identity_db_config(app_config), _identity_db_path(app_config))


def vault_startup_resource(
    engine: SqliteEngine,
    app_config: AppConfig,
    unseal_passphrase: str | None,
) -> Iterator[None]:
    """
    Назначение:
        Resource-генератор для vault DB: schema + unseal + startup guard.

    Контракт:
        - ensure_vault_schema: создать/обновить схему vault.
        - unseal_passphrase: operator-provided secret, не хранится на диске.
        - VaultStartupGuard.ensure_ready(): финальная fail-fast проверка key/probe.
        - yield: container держит engine живым во время runtime.
        - teardown: engine.close().

    Raises:
        VAULT_STARTUP_* при неудачной startup-проверке.
    """
    ensure_vault_schema(engine)
    repository = SqliteVaultRepository(engine)
    cipher = FernetEnvelopeCipher()
    _ = app_config
    guard = VaultStartupGuard(
        repository=repository,
        cipher=cipher,
        key_provider=UnsealedVaultKeyProvider(
            repository=repository,
            unseal_service=VaultUnsealService(),
            passphrase=unseal_passphrase,
        ),
        storage_probe=engine,
    )
    guard.ensure_ready()
    yield
    engine.close()


def vault_schema_resource(engine: SqliteEngine) -> Iterator[None]:
    """
    Назначение:
        Resource-генератор для vault DB без startup guard и maintenance.

    Контракт:
        - Инициализирует только схему vault (`ensure_vault_schema`).
        - Используется manual CLI management-командами (`init/status/rotate/...`),
          где startup-guard управляется на уровне usecase/флагов.
    """
    ensure_vault_schema(engine)
    yield
    engine.close()


def cache_startup_resource(engine: SqliteEngine, specs: list) -> Iterator[None]:
    """
    Назначение:
        Resource-генератор для cache DB: init schema → yield → teardown.
    """
    ensure_cache_ready(engine, specs)
    yield
    engine.close()


def identity_startup_resource(engine: SqliteEngine) -> Iterator[None]:
    """
    Назначение:
        Resource-генератор для identity DB: init schema → yield → teardown.
    """
    ensure_identity_schema(engine)
    yield
    engine.close()


class SqliteContainer(containers.DeclarativeContainer):
    """
    Назначение:
        DI-контейнер для управления lifecycle трёх SQLite-баз данных.

    Lifecycle:
        container.init_resources() — открывает соединения + инициализирует схемы.
        container.shutdown_resources() — закрывает все engine.

    Использование:
        app_config = providers.Dependency(instance_of=AppConfig)
        cache_dir = providers.Dependency(instance_of=str)
        Оба прокидываются при инстанциировании или через override().
    """

    app_config = providers.Dependency(instance_of=AppConfig)
    cache_dir = providers.Dependency(instance_of=str)
    cache_specs = providers.Dependency(instance_of=list)
    unseal_passphrase = providers.Dependency()

    cache_engine = providers.Singleton(
        _make_cache_engine,
        app_config=app_config,
        cache_dir=cache_dir,
    )

    vault_engine = providers.Singleton(
        _make_vault_engine,
        app_config=app_config,
        cache_dir=cache_dir,
    )

    identity_engine = providers.Singleton(
        _make_identity_engine,
        app_config=app_config,
        cache_dir=cache_dir,
    )

    vault_ready = providers.Resource(
        vault_startup_resource,
        engine=vault_engine,
        app_config=app_config,
        unseal_passphrase=unseal_passphrase,
    )

    vault_schema_ready = providers.Resource(
        vault_schema_resource,
        engine=vault_engine,
    )

    cache_ready = providers.Resource(
        cache_startup_resource,
        engine=cache_engine,
        specs=cache_specs,
    )

    identity_ready = providers.Resource(
        identity_startup_resource,
        engine=identity_engine,
    )


# ──────────────────────────────────────────────────────────────────────────────
# DI-контейнер: VaultContainer — vault-сервисы
# ──────────────────────────────────────────────────────────────────────────────


class VaultContainer(containers.DeclarativeContainer):
    """
    Назначение:
        DI-контейнер для vault-сервисов: cipher, key provider, locator,
        repository и per-invocation сервисы (read/write/retention).

    Граница ответственности:
        - vault_engine приходит извне (от SqliteContainer через AppContainer).
        - Stateless объекты (cipher, key_provider, locator, repository) — Singleton.
        - Сервисы с per-invocation state — Factory (новый экземпляр при каждом вызове).
        - read_service принимает default_run_id при вызове: vault.read_service(default_run_id=run_id).

    Контракт:
        - vault_engine должен быть проинициализирован ДО использования сервисов
          (через SqliteContainer.vault_ready.init()).
        - Сервисы не владеют engine — его lifecycle управляется SqliteContainer.
    """

    vault_engine = providers.Dependency(instance_of=SqliteEngine)
    unseal_passphrase = providers.Dependency()

    cipher = providers.Singleton(FernetEnvelopeCipher)
    unseal_service = providers.Singleton(VaultUnsealService)
    locator = providers.Singleton(SecretLocatorService)
    repository = providers.Singleton(
        SqliteVaultRepository,
        engine=vault_engine,
    )
    key_provider = providers.Singleton(
        UnsealedVaultKeyProvider,
        repository=repository,
        unseal_service=unseal_service,
        passphrase=unseal_passphrase,
    )

    read_service = providers.Factory(
        SecretVaultReadService,
        repository=repository,
        cipher=cipher,
        key_provider=key_provider,
        locator=locator,
    )

    write_service = providers.Factory(
        SecretVaultWriteService,
        repository=repository,
        cipher=cipher,
        key_provider=key_provider,
        locator=locator,
    )

    retention_service = providers.Factory(
        VaultRetentionService,
        repository=repository,
        locator=locator,
    )


# ──────────────────────────────────────────────────────────────────────────────
# DI-контейнер: CacheContainer — gateway и role-based порты
# ──────────────────────────────────────────────────────────────────────────────


def cache_gateway_resource(
    cache_engine: SqliteEngine,
    identity_engine: SqliteEngine,
    cache_specs: list,
) -> Iterator[SqliteCacheGateway]:
    """
    Назначение:
        Resource-генератор для SqliteCacheGateway: создание → yield → close.

    Контракт:
        - owns_connection=False: engines не закрываются gateway, их lifecycle у SqliteContainer.
        - gateway.close() только сбрасывает внутренний флаг _closed; engines остаются живыми.
        - ensure_cache_ready вызывается внутри from_engine (идемпотентно).
    """
    gateway = SqliteCacheGateway.from_engine(
        cache_engine=cache_engine,
        identity_engine=identity_engine,
        cache_specs=cache_specs,
        owns_connection=False,
    )
    yield gateway
    gateway.close()


class CacheContainer(containers.DeclarativeContainer):
    """
    Назначение:
        DI-контейнер для cache gateway и role-based портов поверх SQLite engines.

    Граница ответственности:
        - cache_engine и identity_engine приходят извне (от SqliteContainer через AppContainer).
        - gateway — Resource: SqliteCacheGateway с owns_connection=False, teardown через close().
        - roles — Singleton: frozen dataclass SqliteCacheRolePorts, без lifecycle.
        - Engines не закрываются gateway: их lifecycle управляется SqliteContainer.

    Контракт:
        - gateway.init() должен быть вызван ДО обращения к roles().
        - cache_specs передаются от вызывающего кода (содержат спецификации cache-таблиц).
    """

    cache_engine = providers.Dependency(instance_of=SqliteEngine)
    identity_engine = providers.Dependency(instance_of=SqliteEngine)
    cache_specs = providers.Dependency(instance_of=list)

    gateway = providers.Resource(
        cache_gateway_resource,
        cache_engine=cache_engine,
        identity_engine=identity_engine,
        cache_specs=cache_specs,
    )

    roles = providers.Singleton(
        build_sqlite_cache_role_ports,
        gateway=gateway,
    )


# ──────────────────────────────────────────────────────────────────────────────
# DI-контейнер: TargetContainer — lifecycle DefaultTargetRuntime
# ──────────────────────────────────────────────────────────────────────────────


def target_runtime_resource(
    api_settings: ApiConfig,
    transport: object | None,
) -> Iterator[TargetRuntimeBuildResult]:
    """
    Назначение:
        Resource-генератор для TargetRuntime: build → yield → close.

    Контракт:
        - Оборачивает build_target_runtime_with_info() целиком.
        - yield возвращает TargetRuntimeBuildResult (runtime + метаданные).
        - teardown: result.runtime.close() закрывает gateway → driver → httpx.Client.
        - transport=None → реальный HTTP; override в тестах.
    """
    result = build_target_runtime_with_info(api_settings, transport=transport)
    yield result
    result.runtime.close()


class TargetContainer(containers.DeclarativeContainer):
    """
    Назначение:
        DI-контейнер для lifecycle DefaultTargetRuntime.

    Граница ответственности:
        - api_settings и transport приходят извне (от AppContainer).
        - runtime — Resource: build_target_runtime_with_info() целиком,
          teardown через runtime.close().
        - TargetKernel создаётся внутри provider chain (factory.py) —
          не выносится как отдельный провайдер.

    Контракт:
        - runtime.init() должен быть вызван ДО обращения к runtime().
        - transport=None → реальный HTTP; override для тестов.
        - runtime.close() гарантированно вызывается при shutdown_resources().
    """

    api_settings = providers.Dependency(instance_of=ApiConfig)
    transport = providers.Dependency()

    runtime = providers.Resource(
        target_runtime_resource,
        api_settings=api_settings,
        transport=transport,
    )


# ──────────────────────────────────────────────────────────────────────────────
# DI-контейнер: PipelineContainer — lazy transform/planning stages (DEC-004)
# ──────────────────────────────────────────────────────────────────────────────


def _build_transform_context(metadata: PipelineMetadata) -> StageExecutionContext:
    """Scoped context для map/normalize: без capabilities (чистый transform)."""
    return StageExecutionContext(metadata=metadata, capabilities={})


def _build_enrich_context(
    metadata: PipelineMetadata,
    cache_roles: SqliteCacheRolePorts,
    secret_store: object | None,
    dictionaries: object | None,
) -> StageExecutionContext:
    """Scoped context для enrich: EnrichLookupPort + optional secret/dictionary ports."""
    caps: dict[type, object] = {EnrichLookupPort: cache_roles.enrich_lookup}
    if secret_store is not None:
        caps[SecretStoreProtocol] = secret_store
    if dictionaries is not None:
        caps[DictionaryProviderPort] = dictionaries
    return StageExecutionContext(metadata=metadata, capabilities=caps)


def _build_planning_context(
    metadata: PipelineMetadata,
    cache_roles: SqliteCacheRolePorts,
    resolver_settings: object | None,
    topology_provider: TopologyProviderPort | None,
    topology_requirements: TopologyRuntimeRequirements | None,
) -> StageExecutionContext:
    """Scoped context для match/resolve: MatchRuntimePort + ResolveRuntimePort."""
    caps: dict[type, object] = {
        MatchRuntimePort: cache_roles.planning_runtime,
        ResolveRuntimePort: cache_roles.planning_runtime,
    }
    if resolver_settings is not None:
        caps[ResolverSettings] = resolver_settings
    if topology_provider is not None:
        caps[TopologyProviderPort] = topology_provider
    if topology_requirements is not None:
        caps[TopologyRuntimeRequirements] = topology_requirements
    return StageExecutionContext(metadata=metadata, capabilities=caps)


def _compile_resolve_rules(dataset_spec: DatasetSpec) -> object:
    """Compile resolve spec → resolve_rules (needed by match_engine_factory)."""
    resolve_spec = dataset_spec.build_spec_for("resolve")
    sink_spec = dataset_spec.build_spec_for("sink")
    compiled = ResolveDsl().compile(resolve_spec, sink_spec=sink_spec)
    return compiled.resolve_rules


def _create_stage(
    factory: object,
    stage_type: str,
    spec: object,
    ctx: StageExecutionContext,
    **kwargs: Any,
) -> object:
    """Delegate to StageFactory.create() — helper for lambda readability."""
    return factory.create(stage_type, spec, ctx, **kwargs)  # type: ignore[union-attr]


class PipelineContainer(containers.DeclarativeContainer):
    """
    Назначение:
        DI-контейнер для lazy сборки transform/planning stages, orchestrators и
        lifecycle-aware конвейеров (DEC-004, DEC-006, DEC-007).

    Граница ответственности:
        - Owns: lazy Factory providers для stages, contexts, pipeline_composer (DEC-007) и
          planning_pipeline (lifecycle-aware конвейер для import_plan).
        - Does NOT: управлять lifecycle инфраструктуры (это SqliteContainer/CacheContainer).
        - Does NOT: содержать бизнес-логику — только wiring через StageFactory.

    Контракт:
        - Per-command dependencies (dataset_spec, run_id, catalog, etc.)
          задаются через override() context managers в command handlers.
        - Stages материализуются лениво: normalize handler НЕ материализует planning_context.
        - Один экземпляр PipelineContainer на invocation CLI-команды (sub-container AppContainer).
        - planning_pipeline — providers.Factory: PlanningPipeline инкапсулирует
          lifecycle match-runtime scope; lifecycle-логика живёт в PlanningPipeline, не здесь.
        - pipeline_composer — providers.Singleton: держит plain dict с provider-ссылками,
          вызывает их лениво внутри compose() в активном override()-контексте.
    """

    # ── External dependencies (overridden per-command) ────────────────────────

    dataset_spec = providers.Dependency(instance_of=object)
    app_config = providers.Dependency(instance_of=object)
    cache_roles = providers.Dependency(instance_of=object)
    catalog = providers.Dependency(instance_of=object)
    run_id = providers.Dependency(instance_of=str)
    secret_store = providers.Object(None)
    dictionaries = providers.Object(None)
    include_deleted = providers.Object(False)
    topology_provider = providers.Object(None)
    topology_requirements = providers.Object(None)

    # ── Derived metadata ──────────────────────────────────────────────────────

    sink_spec = providers.Factory(
        lambda s: s.build_spec_for("sink"),
        s=dataset_spec,
    )

    pipeline_metadata = providers.Factory(
        PipelineMetadata,
        run_id=run_id,
        dataset_name=providers.Factory(lambda s: s.dataset_name, s=dataset_spec),
        catalog=catalog,
        sink_spec=sink_spec,
    )

    resolver_settings = providers.Factory(
        to_resolver_settings,
        config=app_config,
    )

    # ── Build options (I/O at wiring boundary) ────────────────────────────────

    map_options = providers.Factory(
        lambda s: load_map_build_options_for_dataset(s.dataset_name),
        s=dataset_spec,
    )
    normalize_options = providers.Factory(
        lambda s: load_normalize_build_options_for_dataset(s.dataset_name),
        s=dataset_spec,
    )
    enrich_options = providers.Factory(
        lambda s: load_enrich_build_options_for_dataset(s.dataset_name),
        s=dataset_spec,
    )
    match_options = providers.Factory(
        lambda s: load_match_build_options_for_dataset(s.dataset_name),
        s=dataset_spec,
    )
    resolve_options = providers.Factory(
        lambda s: load_resolve_build_options_for_dataset(s.dataset_name),
        s=dataset_spec,
    )

    # ── Scoped execution contexts ─────────────────────────────────────────────

    transform_context = providers.Factory(
        _build_transform_context,
        metadata=pipeline_metadata,
    )

    enrich_context = providers.Factory(
        _build_enrich_context,
        metadata=pipeline_metadata,
        cache_roles=cache_roles,
        secret_store=secret_store,
        dictionaries=dictionaries,
    )

    planning_context = providers.Factory(
        _build_planning_context,
        metadata=pipeline_metadata,
        cache_roles=cache_roles,
        resolver_settings=resolver_settings,
        topology_provider=topology_provider,
        topology_requirements=topology_requirements,
    )

    # ── Singletons ────────────────────────────────────────────────────────────

    stage_factory = providers.Singleton(build_stage_factory)
    provider_gateway = providers.Singleton(ProviderGateway.with_defaults)

    # ── Per-run state singletons (DEC-004 Stage 4) ────────────────────────────

    _dedup_store = providers.Singleton(LocalSourceDedupStore)
    _batch_index = providers.Singleton(InMemoryBatchIndexService)
    pending_codec = providers.Singleton(PendingCodecAdapter)
    pending_expiry = providers.Singleton(
        PendingExpiryService,
        cache_gateway=providers.Factory(lambda roles: roles.planning_runtime, roles=cache_roles),
        settings=resolver_settings,
    )
    match_batch_settings = providers.Singleton(
        MatchBatchSettings,
        batch_size=providers.Factory(
            lambda s: s.matching_runtime.match_batch_size, s=app_config
        ),
        flush_interval_ms=providers.Factory(
            lambda s: s.matching_runtime.match_flush_interval_ms, s=app_config
        ),
    )

    match_scope = providers.Singleton(
        MatchScopeService,
        match_runtime=providers.Factory(
            lambda roles: roles.planning_runtime, roles=cache_roles
        ),
        run_id=run_id,
    )

    plan_hooks = providers.Singleton(
        PlanningPipelineHooks,
        pending_expiry=pending_expiry,
        match_scope=match_scope,
    )
    resolve_stage_hooks = providers.Singleton(
        lambda hooks: hooks.plan_hooks(),
        hooks=plan_hooks,
    )

    run_context = providers.Singleton(
        PipelineRunContext,
        dedup_store=_dedup_store,
        batch_index=_batch_index,
    )

    # ── Compiled resolve rules (for match kwargs) ─────────────────────────────

    compiled_resolve_rules = providers.Factory(
        _compile_resolve_rules,
        dataset_spec=dataset_spec,
    )

    # ── Row source ────────────────────────────────────────────────────────────

    row_source = providers.Factory(
        lambda s: s.build_record_source(),
        s=dataset_spec,
    )

    # ── Transform stages ──────────────────────────────────────────────────────

    map_stage = providers.Factory(
        _create_stage,
        factory=stage_factory,
        stage_type="map",
        spec=providers.Factory(lambda s: s.build_spec_for("map"), s=dataset_spec),
        ctx=transform_context,
        options=map_options,
    )

    row_builder = providers.Factory(
        lambda s: getattr(s, "row_builder", None),
        s=dataset_spec,
    )

    normalize_stage = providers.Factory(
        _create_stage,
        factory=stage_factory,
        stage_type="normalize",
        spec=providers.Factory(lambda s: s.build_spec_for("normalize"), s=dataset_spec),
        ctx=transform_context,
        options=normalize_options,
        row_builder=row_builder,
    )

    enrich_stage = providers.Factory(
        _create_stage,
        factory=stage_factory,
        stage_type="enrich",
        spec=providers.Factory(lambda s: s.build_spec_for("enrich"), s=dataset_spec),
        ctx=enrich_context,
        options=enrich_options,
        gateway=provider_gateway,
    )

    # ── Planning stages ───────────────────────────────────────────────────────

    # MatchEngine — Singleton (аналогично _resolve_engine): MatchStage создаётся
    # напрямую в PipelineContainer, т.к. требует batch_settings (Variant B, DEC-002).
    _match_engine = providers.Singleton(
        MatchEngine,
        spec=providers.Factory(lambda s: s.build_spec_for("match"), s=dataset_spec),
        ctx=planning_context,
        resolve_rules=compiled_resolve_rules,
        include_deleted=include_deleted,
        options=match_options,
        dedup_store=_dedup_store,
    )

    match_stage = providers.Singleton(
        MatchStage,
        matcher=_match_engine,
        catalog=catalog,
        batch_settings=match_batch_settings,
    )

    # ── Resolve engine (Singleton, shared between ResolveContextStage и ResolveStage)
    _resolve_engine = providers.Singleton(
        ResolveEngine,
        spec=providers.Factory(lambda s: s.build_spec_for("resolve"), s=dataset_spec),
        ctx=planning_context,
        options=resolve_options,
        codec=pending_codec,
    )

    resolve_context_stage = providers.Singleton(
        ResolveContextStage,
        batch_index=_batch_index,
        resolver=_resolve_engine,
    )

    resolve_stage = providers.Singleton(
        ResolveStage,
        resolver=_resolve_engine,
        catalog=catalog,
        batch_index=_batch_index,
    )

    # ── Orchestrators / pipelines ─────────────────────────────────────────────

    # pipeline_composer: declarative checkpoint assembly (DEC-007).
    # stage_registry is a plain dict (not providers.Dict) so provider-callables
    # remain lazy — compose() calls them inside the active override() context.
    pipeline_composer = providers.Singleton(
        PipelineComposer,
        stage_registry={
            StageName.MAP: map_stage,
            StageName.NORMALIZE: normalize_stage,
            StageName.ENRICH: enrich_stage,
            StageName.MATCH: match_stage,
            StageName.RESOLVE_CONTEXT: resolve_context_stage,
            StageName.RESOLVE: resolve_stage,
        },
        checkpoints=providers.Object(PIPELINE_CHECKPOINTS),
    )

    planning_pipeline = providers.Factory(
        PlanningPipeline,
        composer=pipeline_composer,
        plan_hooks=resolve_stage_hooks,
        resolve_stage=resolve_stage,
        pending_expiry=pending_expiry,
        dedup_store=_dedup_store,
        row_source=row_source,
        catalog=catalog,
        dataset_spec=dataset_spec,
        app_config=app_config,
    )


# ──────────────────────────────────────────────────────────────────────────────
# DI-контейнер: AppContainer — единый Composition Root
# ──────────────────────────────────────────────────────────────────────────────


class AppContainer(containers.DeclarativeContainer):
    """
    Назначение:
        Единый Composition Root: монтирует все sub-containers и предоставляет
        точку входа для CLI-команд.

    Граница ответственности:
        - Создаётся ТОЛЬКО в run_with_report() / run_without_report().
        - shutdown_resources() вызывается в finally — закрывает все ресурсы.
        - Один экземпляр на invocation CLI-команды.
        - Не содержит бизнес-логики — только сборка графа зависимостей.

    Контракт:
        - app_config должен быть проброшен через override() до init.
        - _init_container_for_requirements() инициализирует нужные ресурсы
          на основе Requirements команды.
    """

    app_config = providers.Dependency(instance_of=AppConfig)
    vault_unseal_passphrase = providers.Object(None)

    _cache_dir = providers.Callable(lambda s: s.paths.cache_dir, s=app_config)
    _api_settings = providers.Callable(lambda s: s.api, s=app_config)
    _dictionary_cfg = providers.Callable(lambda s: s.dictionary, s=app_config)
    _dataset_registry_path = providers.Callable(to_dataset_registry_path, config=app_config)
    _dictionary_specs_root = providers.Callable(
        lambda s: str(_runtime_paths_for(s).dictionary_specs_root),
        s=app_config,
    )
    _dictionary_data_root = providers.Callable(
        lambda s: str(_runtime_paths_for(s).dictionary_data_root),
        s=app_config,
    )
    _vault_management_settings = providers.Callable(to_vault_management_settings, config=app_config)

    cache_dsl = providers.Singleton(load_cache_dsl_runtime)
    _cache_specs = providers.Callable(lambda b: list(b.cache_specs), b=cache_dsl)

    sqlite = providers.Container(
        SqliteContainer,
        app_config=app_config,
        cache_dir=_cache_dir,
        cache_specs=_cache_specs,
        unseal_passphrase=vault_unseal_passphrase,
    )

    cache = providers.Container(
        CacheContainer,
        cache_engine=sqlite.cache_engine,
        identity_engine=sqlite.identity_engine,
        cache_specs=_cache_specs,
    )

    vault = providers.Container(
        VaultContainer,
        vault_engine=sqlite.vault_engine,
        unseal_passphrase=vault_unseal_passphrase,
    )

    vault_admin_password_gate = providers.Singleton(
        VaultAdminPasswordGate,
        require_admin_password_for_manual_ops=providers.Callable(
            lambda s: s.require_admin_password_for_manual_ops,
            s=_vault_management_settings,
        ),
        admin_password_hash_file=providers.Callable(
            lambda s: s.admin_password_hash_file,
            s=_vault_management_settings,
        ),
        admin_password_hash_name=providers.Callable(
            lambda s: s.admin_password_hash_name,
            s=_vault_management_settings,
        ),
        admin_password_env_var=providers.Callable(
            lambda s: s.admin_password_env_var,
            s=_vault_management_settings,
        ),
    )

    vault_post_verifier = providers.Factory(
        VaultStartupGuardPostVerifier,
        repository=vault.repository,
        cipher=vault.cipher,
        storage_probe=sqlite.vault_engine,
    )

    vault_key_management_usecase = providers.Factory(
        VaultKeyManagementUseCase,
        repository=vault.repository,
        cipher=vault.cipher,
        unseal_service=vault.unseal_service,
        post_verify=vault_post_verifier,
    )

    target = providers.Container(
        TargetContainer,
        api_settings=_api_settings,
        transport=providers.Object(None),
    )

    dictionary = providers.Container(
        DictionaryContainer,
        settings=_dictionary_cfg,
        registry_path=_dataset_registry_path,
        dictionary_specs_root=_dictionary_specs_root,
        dictionary_data_root=_dictionary_data_root,
    )

    pipeline = providers.Container(
        PipelineContainer,
        app_config=app_config,
        cache_roles=cache.roles,
    )


def _init_container_for_requirements(
    container: AppContainer,
    req: Requirements,
) -> None:
    """
    Назначение:
        Инициализировать ресурсы контейнера согласно декларативным требованиям команды.

    Контракт:
        - requires_cache: открывает cache/identity engines + schema + gateway.
        - requires_vault_schema: открывает vault engine + schema (без startup guard).
        - requires_vault_init: открывает vault engine + schema + VaultStartupGuard.
        - requires_api: создаёт target runtime (HTTP-клиент + gateway).
        - requires_dictionaries: eager-init dictionary backend Resource и, если runtime активен,
          пробрасывает capability в PipelineContainer через `pipeline.dictionaries`.
        - Вызывается ОДИН раз перед handler_fn() в run_with_report().
    """
    if req.requires_cache:
        container.sqlite.cache_ready.init()
        container.sqlite.identity_ready.init()
        container.cache.gateway.init()
    if req.requires_vault_init:
        container.sqlite.vault_ready.init()
    elif req.requires_vault_schema:
        container.sqlite.vault_schema_ready.init()
    if req.requires_api:
        container.target.runtime.init()
    if req.requires_dictionaries:
        container.dictionary.backend.init()
        dictionary_provider = container.dictionary.provider()
        if dictionary_provider is not None:
            container.pipeline.dictionaries.override(dictionary_provider)


# ──────────────────────────────────────────────────────────────────────────────
# Диагностика / датасеты
# ──────────────────────────────────────────────────────────────────────────────


def build_diagnostics_catalog(dataset: str | None, *, strict: bool):
    """
    Назначение:
        Сконфигурировать диагностический каталог для выбранного датасета.
    Контракт:
        - dataset=None -> core catalog
        - dataset указан -> core + dataset catalog
    """
    return build_catalog(dataset, strict=strict)


def build_dataset_spec(
    dataset: str | None,
    dataset_settings: DatasetConfig,
    *,
    secrets: SecretProviderProtocol | None = None,
):
    """
    Назначение:
        Разрешить имя датасета и вернуть соответствующий DatasetSpec.

    Контракт:
        - validate_registry() вызывается eagerly: ошибки в spec_class
          обнаруживаются при старте, а не при первом get_spec().
    """
    validate_registry()
    dataset_name = resolve_dataset_name(dataset, dataset_settings.dataset_name)
    return dataset_name, get_spec(dataset_name, secrets=secrets)



__all__ = [
    "SqliteContainer",
    "VaultContainer",
    "CacheContainer",
    "TargetContainer",
    "PipelineContainer",
    "AppContainer",
    "_init_container_for_requirements",
    "build_diagnostics_catalog",
    "build_dataset_spec",
]
