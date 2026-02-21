"""
Назначение:
    Composition Root для CLI-приложения: DI-контейнеры и AppContainer.

    Модуль содержит иерархию DI-контейнеров для управления lifecycle
    инфраструктурных ресурсов (SQLite engines, vault services, cache gateway,
    HTTP target runtime).

    AppContainer — единый CR, создаётся в run_with_report() / run_without_report().
    Command handlers получают зависимости через ctx.container.*.

Граница ответственности:
    - SqliteContainer: lifecycle трёх SQLite engines (cache, vault, identity).
    - VaultContainer: vault-сервисы (cipher, read/write/retention) поверх vault_engine.
    - CacheContainer: cache gateway (Resource) + role-based порты (Singleton).
    - TargetContainer: lifecycle DefaultTargetRuntime (HTTP-клиент + gateway).
    - AppContainer: монтирует все sub-containers; единственный CR.
    - _init_container_for_requirements(): условная инициализация ресурсов по Requirements.
    - build_diagnostics_catalog(), build_dataset_spec(): stateless утилиты.
    - PipelineContext, build_pipeline_context(): сборка transform pipeline
      (будет вынесена в PipelineContainer, TRANSFORM-DEC-003).
    - Никакой доменной логики — только сборка графа зависимостей.

Зависимости:
    Единственный модуль вне infra/, которому разрешено импортировать
    connector.infra.secrets.*, connector.infra.cache.*, connector.infra.sqlite.*
    для сборки DI-графа.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from dependency_injector import containers, providers

from connector.config.app_settings import (
    ApiSettings,
    AppSettings,
    DatasetSettings,
    ObservabilitySettings,
    SqliteSettings,
    build_cache_db_config,
    build_identity_db_config,
    build_vault_db_config,
)
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.domain.diagnostics import build_catalog
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.ports.transform.dictionaries import DictionaryProviderPort
from connector.domain.secrets.secret_locator_service import SecretLocatorService
from connector.domain.secrets.vault_retention_service import VaultRetentionService
from connector.domain.secrets.secret_vault_read_service import SecretVaultReadService
from connector.domain.secrets.secret_vault_write_service import SecretVaultWriteService
from connector.domain.secrets.vault_startup_guard import VaultStartupGuard
from connector.datasets.registry import get_spec, resolve_dataset_name
from connector.datasets.spec import DatasetSpec
from connector.domain.transform.stages.stages import StagePipeline, MapStage, NormalizeStage, EnrichStage
from connector.domain.transform.resolver.resolve_deps import PlanningDependencies
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.cache.dsl_runtime import load_cache_dsl_runtime
from connector.infra.cache.roles import SqliteCacheRolePorts, build_sqlite_cache_role_ports
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.identity.sqlite.schema import ensure_identity_schema
from connector.infra.secrets import (
    EnvVaultKeyProvider,
    FernetEnvelopeCipher,
)
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.secrets.sqlite.schema import ensure_vault_schema
from connector.infra.sqlite.engine import SqliteEngine, open_sqlite
from connector.infra.target.core.factory import (
    TargetRuntimeBuildResult,
    build_target_runtime_with_info,
)


# ──────────────────────────────────────────────────────────────────────────────
# Path helpers (inline — no legacy db.py dependency)
# ──────────────────────────────────────────────────────────────────────────────


def _cache_db_path(cache_dir: str) -> str:
    return str(Path(cache_dir) / "ankey_cache.sqlite3")


def _vault_db_path(cache_dir: str, settings: SqliteSettings) -> str:
    if settings.vault_db_path:
        return settings.vault_db_path
    return str(Path(cache_dir) / "ankey_vault.sqlite3")


def _identity_db_path(cache_dir: str, settings: SqliteSettings) -> str:
    if settings.identity_db_path:
        return settings.identity_db_path
    return str(Path(cache_dir) / "identity.sqlite3")


# ──────────────────────────────────────────────────────────────────────────────
# DI-контейнер: управление lifecycle SqliteEngine
# ──────────────────────────────────────────────────────────────────────────────


def _make_cache_engine(settings: SqliteSettings, cache_dir: str) -> SqliteEngine:
    return open_sqlite(build_cache_db_config(settings), _cache_db_path(cache_dir))


def _make_vault_engine(settings: SqliteSettings, cache_dir: str) -> SqliteEngine:
    return open_sqlite(build_vault_db_config(settings), _vault_db_path(cache_dir, settings))


def _make_identity_engine(settings: SqliteSettings, cache_dir: str) -> SqliteEngine:
    return open_sqlite(build_identity_db_config(settings), _identity_db_path(cache_dir, settings))


def vault_startup_resource(engine: SqliteEngine) -> Iterator[None]:
    """
    Назначение:
        Resource-генератор для vault DB: init schema + startup guard → yield → teardown.

    Контракт:
        - ensure_vault_schema: создать/обновить схему vault.
        - VaultStartupGuard.ensure_ready(): fail-fast проверка keyring/probe.
        - yield: container держит engine живым во время runtime.
        - teardown: engine.close().

    Raises:
        VAULT_STARTUP_* при неудачной startup-проверке.
    """
    ensure_vault_schema(engine)
    guard = VaultStartupGuard(
        repository=SqliteVaultRepository(engine),
        cipher=FernetEnvelopeCipher(),
        key_provider=EnvVaultKeyProvider(),
        storage_probe=engine,
    )
    guard.ensure_ready()
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
        settings = providers.Dependency(instance_of=SqliteSettings)
        cache_dir = providers.Dependency(instance_of=str)
        Оба прокидываются при инстанциировании или через override().
    """

    settings = providers.Dependency(instance_of=SqliteSettings)
    cache_dir = providers.Dependency(instance_of=str)
    cache_specs = providers.Dependency(instance_of=list)

    cache_engine = providers.Singleton(
        _make_cache_engine,
        settings=settings,
        cache_dir=cache_dir,
    )

    vault_engine = providers.Singleton(
        _make_vault_engine,
        settings=settings,
        cache_dir=cache_dir,
    )

    identity_engine = providers.Singleton(
        _make_identity_engine,
        settings=settings,
        cache_dir=cache_dir,
    )

    vault_ready = providers.Resource(
        vault_startup_resource,
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

    cipher = providers.Singleton(FernetEnvelopeCipher)
    key_provider = providers.Singleton(EnvVaultKeyProvider)
    locator = providers.Singleton(SecretLocatorService)
    repository = providers.Singleton(
        SqliteVaultRepository,
        engine=vault_engine,
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
    api_settings: ApiSettings,
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

    api_settings = providers.Dependency(instance_of=ApiSettings)
    transport = providers.Dependency()

    runtime = providers.Resource(
        target_runtime_resource,
        api_settings=api_settings,
        transport=transport,
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
        - app_settings должен быть проброшен через override() до init.
        - _init_container_for_requirements() инициализирует нужные ресурсы
          на основе Requirements команды.
    """

    app_settings = providers.Dependency(instance_of=AppSettings)

    _sqlite_cfg = providers.Singleton(SqliteSettings)
    _cache_dir = providers.Callable(lambda s: s.paths.cache_dir, s=app_settings)
    _api_settings = providers.Callable(lambda s: s.api, s=app_settings)

    cache_dsl = providers.Singleton(load_cache_dsl_runtime)
    _cache_specs = providers.Callable(lambda b: list(b.cache_specs), b=cache_dsl)

    sqlite = providers.Container(
        SqliteContainer,
        settings=_sqlite_cfg,
        cache_dir=_cache_dir,
        cache_specs=_cache_specs,
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
    )

    target = providers.Container(
        TargetContainer,
        api_settings=_api_settings,
        transport=providers.Object(None),
    )


def _init_container_for_requirements(
    container: AppContainer,
    req: "Requirements",
) -> None:
    """
    Назначение:
        Инициализировать ресурсы контейнера согласно декларативным требованиям команды.

    Контракт:
        - requires_cache: открывает cache/identity engines + schema + gateway.
        - requires_vault_init: открывает vault engine + schema + VaultStartupGuard.
        - requires_api: создаёт target runtime (HTTP-клиент + gateway).
        - Вызывается ОДИН раз перед handler_fn() в run_with_report().
    """
    if req.requires_cache:
        container.sqlite.cache_ready.init()
        container.sqlite.identity_ready.init()
        container.cache.gateway.init()
    if req.requires_vault_init:
        container.sqlite.vault_ready.init()
    if req.requires_api:
        container.target.runtime.init()


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
    dataset_settings: DatasetSettings,
    *,
    secrets: SecretProviderProtocol | None = None,
):
    """
    Назначение:
        Разрешить имя датасета и вернуть соответствующий DatasetSpec.
    """
    dataset_name = resolve_dataset_name(dataset, dataset_settings.dataset_name)
    return dataset_name, get_spec(dataset_name, secrets=secrets)


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline context (TRANSFORM-DEC-003 — будет вынесен в отдельный контейнер)
# ──────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PipelineContext:
    """
    Назначение:
        Собранный контекст transform-пайплайна для CLI use-cases.

    Контракт:
        Используется как единый источник для map/normalize/enrich.
    """

    dataset_name: str
    catalog: ErrorCatalog
    row_source: Iterable
    map_stage: MapStage
    normalize_stage: NormalizeStage
    enrich_stage: EnrichStage
    stage_pipeline: StagePipeline
    planning_deps: PlanningDependencies
    report_items_limit: int


def build_pipeline_context(
    *,
    dataset_spec: DatasetSpec,
    dataset_name: str,
    cache_roles: SqliteCacheRolePorts,
    resolver_settings: ResolverSettings | None,
    observability_settings: ObservabilitySettings,
    catalog: ErrorCatalog,
    csv_has_header: bool,
    secret_store: Any | None = None,
    dictionaries: DictionaryProviderPort | None = None,
) -> PipelineContext:
    """
    Назначение:
        Единая сборка map/normalize/enrich цепочки.
    """
    enrich_deps = dataset_spec.build_enrich_deps(
        None,
        enrich_lookup=cache_roles.enrich_lookup,
        secret_store=secret_store,
        dictionaries=dictionaries,
    )
    planning_deps = dataset_spec.build_planning_deps(
        resolver_settings,
        planning_runtime=cache_roles.planning_runtime,
    )

    map_stage, normalize_stage, enrich_stage = dataset_spec.build_transform_stages(
        enrich_deps=enrich_deps,
        catalog=catalog,
    )

    row_source = dataset_spec.build_record_source(csv_has_header=csv_has_header)

    stage_pipeline = StagePipeline(
        [
            map_stage,
            normalize_stage,
            enrich_stage,
        ]
    )

    return PipelineContext(
        dataset_name=dataset_name,
        catalog=catalog,
        row_source=row_source,
        map_stage=map_stage,
        normalize_stage=normalize_stage,
        enrich_stage=enrich_stage,
        stage_pipeline=stage_pipeline,
        planning_deps=planning_deps,
        report_items_limit=observability_settings.report_items_limit,
    )


__all__ = [
    "SqliteContainer",
    "VaultContainer",
    "CacheContainer",
    "TargetContainer",
    "AppContainer",
    "_init_container_for_requirements",
    "build_diagnostics_catalog",
    "build_dataset_spec",
    "PipelineContext",
    "build_pipeline_context",
]
