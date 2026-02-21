"""
Назначение:
    Composition root для CLI: DI-контейнеры (SqliteContainer, VaultContainer) +
    utility-функции для сборки pipeline-компонентов.

    Заменяет bootstrap.py — единственный модуль outside infra/,
    которому разрешено импортировать connector.infra.secrets.*.

Граница ответственности:
    - SqliteContainer управляет lifecycle SqliteEngine (Singleton + Resource teardown).
    - VaultContainer предоставляет vault-сервисы (cipher, read/write/retention)
      поверх vault_engine из SqliteContainer.
    - Utility-функции (build_cache, open_cache, ensure_vault_startup_ready…)
      остаются как transitional wiring — будут удалены по мере миграции
      команд на AppContainer (DELIVERY-DEC-006/007).
    - Никакой доменной логики — только сборка графа зависимостей.
"""
from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator

from dependency_injector import containers, providers

from connector.config.app_settings import (
    DatasetSettings,
    ObservabilitySettings,
    PathsSettings,
    SqliteSettings,
    build_cache_db_config,
    build_identity_db_config,
    build_vault_db_config,
)
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.domain.diagnostics import build_catalog
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.secrets.provider import SecretProviderProtocol, SecretStoreProtocol
from connector.domain.ports.secrets.retention import SecretApplyRetentionHookProtocol
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
from connector.infra.cache.dsl_runtime import CacheDslRuntimeBundle, load_cache_dsl_runtime
from connector.infra.cache.roles import SqliteCacheRolePorts, build_sqlite_cache_role_ports
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.identity.sqlite.schema import ensure_identity_schema
from connector.infra.secrets import (
    EnvVaultKeyProvider,
    FernetEnvelopeCipher,
    NullSecretProvider,
    PromptSecretProvider,
)
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.secrets.sqlite.schema import ensure_vault_schema
from connector.infra.sqlite.engine import SqliteEngine, open_sqlite
from connector.infra.target.core.factory import (
    build_target_runtime,  # noqa: F401 — re-export
    build_target_runtime_with_info,  # noqa: F401 — re-export
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
# Vault engine helper (used by legacy wiring functions below)
# Deprecated: будет удалено в DELIVERY-DEC-007 (Шаг 6)
# ──────────────────────────────────────────────────────────────────────────────


def _open_vault_engine(paths_settings: PathsSettings) -> SqliteEngine:
    """Открыть SqliteEngine для vault DB с политикой из SqliteSettings.

    Deprecated: используется legacy wiring (open_secret_store, build_secret_provider,
    build_secret_retention_hook). Будет удалено в DELIVERY-DEC-007 (Шаг 6).
    """
    settings = SqliteSettings()
    config = build_vault_db_config(settings)
    path = _vault_db_path(paths_settings.cache_dir, settings)
    return open_sqlite(config, path)


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
# Cache gateway wiring
# ──────────────────────────────────────────────────────────────────────────────


def build_cache(
    paths_settings: PathsSettings,
) -> tuple[SqliteCacheGateway, SqliteCacheRolePorts, CacheDslRuntimeBundle]:
    """
    Назначение:
        Сконфигурировать cache-хранилище (sqlite) и репозиторий.

    Lifecycle (DELIVERY-DEC-002):
        Engines создаются и управляются SqliteContainer (Singleton + Resource teardown).
        gateway.close() вызывает container.shutdown_resources() для корректного
        закрытия engines. Vault engine НЕ инициализируется.

    Transitional:
        Будет заменено CacheContainer в DELIVERY-DEC-004 (Шаг 3).
    """
    sqlite_settings = SqliteSettings()
    cache_dsl_bundle = load_cache_dsl_runtime()

    container = SqliteContainer()
    container.settings.override(sqlite_settings)
    container.cache_dir.override(paths_settings.cache_dir)
    container.cache_specs.override(list(cache_dsl_bundle.cache_specs))

    container.cache_ready.init()
    container.identity_ready.init()

    cache_engine = container.cache_engine()
    identity_engine = container.identity_engine()

    gateway = SqliteCacheGateway.from_engine(
        cache_engine=cache_engine,
        identity_engine=identity_engine,
        cache_specs=cache_dsl_bundle.cache_specs,
        owns_connection=False,
    )
    roles = build_sqlite_cache_role_ports(gateway)

    _original_close = gateway.close
    _shutdown_done = False

    def _close_with_container_shutdown() -> None:
        nonlocal _shutdown_done
        _original_close()
        if not _shutdown_done:
            container.shutdown_resources()
            _shutdown_done = True

    gateway.close = _close_with_container_shutdown  # type: ignore[method-assign]

    return gateway, roles, cache_dsl_bundle


@contextmanager
def open_cache(
    paths_settings: PathsSettings,
) -> Iterator[tuple[SqliteCacheGateway, SqliteCacheRolePorts, CacheDslRuntimeBundle]]:
    """
    Назначение:
        Единая lifecycle-обертка для cache gateway в CLI runtime.
    """
    gateway, roles, cache_dsl_bundle = build_cache(paths_settings)
    try:
        yield gateway, roles, cache_dsl_bundle
    finally:
        gateway.close()


# ──────────────────────────────────────────────────────────────────────────────
# Vault startup guard
# Deprecated: логика поглощена vault_startup_resource() в SqliteContainer.
# Будет удалено в DELIVERY-DEC-007 (Шаг 6) после миграции handlers.
# ──────────────────────────────────────────────────────────────────────────────


def ensure_vault_startup_ready(*, paths_settings: PathsSettings) -> None:
    """
    Назначение:
        Выполнить startup fail-fast проверку vault перед запуском use-case в vault-mode.

    Deprecated:
        Логика поглощена vault_startup_resource() (VaultStartupGuard включён).
        Будет удалено после миграции handlers на AppContainer (DELIVERY-DEC-007).

    Контракт:
        - открывает отдельное vault DB соединение;
        - валидирует keyring/probe/storage через VaultStartupGuard;
        - всегда закрывает соединение в конце проверки.
    """
    engine = _open_vault_engine(paths_settings)
    try:
        guard = VaultStartupGuard(
            repository=SqliteVaultRepository(engine),
            cipher=FernetEnvelopeCipher(),
            key_provider=EnvVaultKeyProvider(),
            storage_probe=engine,
        )
        guard.ensure_ready()
    finally:
        engine.close()


# ──────────────────────────────────────────────────────────────────────────────
# Vault secret store (write) lifecycle
# ──────────────────────────────────────────────────────────────────────────────


@contextmanager
def open_secret_store(
    *,
    paths_settings: PathsSettings,
    enabled: bool,
) -> Iterator[SecretStoreProtocol | None]:
    """
    Назначение:
        Собрать lifecycle write-store для секрета в vault backend.

    Контракт:
        - при `enabled=False` возвращает `None` без инициализации vault-зависимостей;
        - при `enabled=True` открывает отдельный vault DB и закрывает его по завершении.
    """
    if not enabled:
        yield None
        return

    engine = _open_vault_engine(paths_settings)
    try:
        store = SecretVaultWriteService(
            repository=SqliteVaultRepository(engine),
            cipher=FernetEnvelopeCipher(),
            key_provider=EnvVaultKeyProvider(),
            locator=SecretLocatorService(),
        )
        yield store
    finally:
        engine.close()


# ──────────────────────────────────────────────────────────────────────────────
# Vault read/retention runtimes
# Deprecated: заменяются VaultContainer (Factory providers для read/write/retention).
# Engine lifecycle управляется SqliteContainer.vault_engine Singleton.
# Будут удалены в DELIVERY-DEC-007 (Шаг 6) после миграции handlers.
# ──────────────────────────────────────────────────────────────────────────────


class _VaultReadProviderRuntime(SecretProviderProtocol):
    """
    Назначение:
        Runtime-обёртка vault read provider c управлением lifecycle SQLite connection.

    Deprecated:
        Заменяется VaultContainer.read_service (Factory). Engine lifecycle
        управляется SqliteContainer.vault_engine Singleton.
        Будет удалено в DELIVERY-DEC-007 (Шаг 6).

    Граница:
        Наружу публикуется только `SecretProviderProtocol` + `close()` для composition-root.
    """

    def __init__(self, *, paths_settings: PathsSettings, run_id: str | None) -> None:
        self._engine = _open_vault_engine(paths_settings)
        self._provider = SecretVaultReadService(
            repository=SqliteVaultRepository(self._engine),
            cipher=FernetEnvelopeCipher(),
            key_provider=EnvVaultKeyProvider(),
            locator=SecretLocatorService(),
            default_run_id=run_id,
        )

    def get_secret(
        self,
        *,
        dataset: str,
        field: str,
        row_id: str | None = None,
        line_no: int | None = None,
        source_ref: dict | None = None,
        target_id: str | None = None,
        run_id: str | None = None,
    ) -> str | None:
        return self._provider.get_secret(
            dataset=dataset,
            field=field,
            row_id=row_id,
            line_no=line_no,
            source_ref=source_ref,
            target_id=target_id,
            run_id=run_id,
        )

    def close(self) -> None:
        self._engine.close()


class _VaultRetentionRuntime(SecretApplyRetentionHookProtocol):
    """
    Назначение:
        Runtime-обёртка retention/maintenance hooks с lifecycle SQLite connection.

    Deprecated:
        Заменяется VaultContainer.retention_service (Factory).
        Будет удалено в DELIVERY-DEC-007 (Шаг 6).
    """

    def __init__(self, *, paths_settings: PathsSettings) -> None:
        self._engine = _open_vault_engine(paths_settings)
        self._service = VaultRetentionService(
            repository=SqliteVaultRepository(self._engine),
            locator=SecretLocatorService(),
        )

    def on_apply_success(
        self,
        *,
        dataset: str,
        op: str,
        source_ref: dict[str, Any] | None,
        secret_fields: list[str],
        secret_lifecycle: dict[str, Any] | None,
        run_id: str | None,
    ) -> dict[str, int]:
        return dict(
            self._service.on_apply_success(
                dataset=dataset,
                op=op,
                source_ref=source_ref,
                secret_fields=secret_fields,
                secret_lifecycle=secret_lifecycle,
                run_id=run_id,
            )
        )

    def run_maintenance(self) -> dict[str, int]:
        return dict(self._service.run_maintenance())

    def close(self) -> None:
        self._engine.close()


def build_secret_provider(
    source: str | None,
    *,
    paths_settings: PathsSettings | None = None,
    run_id: str | None = None,
) -> SecretProviderProtocol:
    """
    Назначение:
        Фабрика провайдера секретов для apply.

    Контракт:
        - source None/"none" -> NullSecretProvider
        - source "prompt" -> PromptSecretProvider
        - source "vault" -> vault-only SecretVaultReadService (без prompt/CSV fallback)
        - любое другое значение -> NullSecretProvider
    """
    if not source or source == "none":
        return NullSecretProvider()
    if source == "prompt":
        return PromptSecretProvider()
    if source == "vault":
        if paths_settings is None:
            raise ValueError("paths_settings is required for source='vault'")
        return _VaultReadProviderRuntime(paths_settings=paths_settings, run_id=run_id)
    return NullSecretProvider()


def build_secret_retention_hook(
    source: str | None,
    *,
    paths_settings: PathsSettings | None = None,
) -> SecretApplyRetentionHookProtocol | None:
    """
    Назначение:
        Собрать retention hook для apply-runtime в vault-mode.
    """
    if source != "vault":
        return None
    if paths_settings is None:
        raise ValueError("paths_settings is required for source='vault'")
    return _VaultRetentionRuntime(paths_settings=paths_settings)


# ──────────────────────────────────────────────────────────────────────────────
# Pipeline context
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
    "build_diagnostics_catalog",
    "build_dataset_spec",
    "build_cache",
    "open_cache",
    "open_secret_store",
    "ensure_vault_startup_ready",
    "build_target_runtime",
    "build_target_runtime_with_info",
    "build_secret_provider",
    "build_secret_retention_hook",
    "PipelineContext",
    "build_pipeline_context",
]
