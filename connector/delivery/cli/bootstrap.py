from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

from connector.config.app_settings import (
    DatasetSettings,
    ObservabilitySettings,
    PathsSettings,
    PendingSettings,
)
from connector.domain.diagnostics import build_catalog
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.secrets.provider import SecretProviderProtocol, SecretStoreProtocol
from connector.domain.ports.secrets.retention import SecretApplyRetentionHookProtocol
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
from connector.infra.secrets import (
    EnvVaultKeyProvider,
    FernetEnvelopeCipher,
    NullSecretProvider,
    PromptSecretProvider,
)
from connector.infra.secrets.sqlite import SqliteVaultRepository, VaultSqliteDb
from connector.infra.target.core.factory import (
    build_target_runtime,  # noqa: F401 — re-export
    build_target_runtime_with_info,  # noqa: F401 — re-export
)


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


def build_cache(
    paths_settings: PathsSettings,
) -> tuple[SqliteCacheGateway, SqliteCacheRolePorts, CacheDslRuntimeBundle]:
    """
    Назначение:
        Сконфигурировать cache-хранилище (sqlite) и репозиторий.
    """
    cache_dsl_bundle = load_cache_dsl_runtime()
    gateway = SqliteCacheGateway.open(
        cache_dir=paths_settings.cache_dir,
        cache_specs=cache_dsl_bundle.cache_specs,
    )
    roles = build_sqlite_cache_role_ports(gateway)
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

    vault_db = VaultSqliteDb(cache_dir=paths_settings.cache_dir)
    try:
        repository = SqliteVaultRepository(vault_db)
        store = SecretVaultWriteService(
            repository=repository,
            cipher=FernetEnvelopeCipher(),
            key_provider=EnvVaultKeyProvider(),
            locator=SecretLocatorService(),
        )
        yield store
    finally:
        vault_db.close()


def ensure_vault_startup_ready(*, paths_settings: PathsSettings) -> None:
    """
    Назначение:
        Выполнить startup fail-fast проверку vault перед запуском use-case в vault-mode.

    Контракт:
        - открывает отдельное vault DB соединение;
        - валидирует keyring/probe/storage через `VaultStartupGuard`;
        - всегда закрывает соединение в конце проверки.
    """
    vault_db = VaultSqliteDb(cache_dir=paths_settings.cache_dir)
    try:
        guard = VaultStartupGuard(
            repository=SqliteVaultRepository(vault_db),
            cipher=FernetEnvelopeCipher(),
            key_provider=EnvVaultKeyProvider(),
        )
        guard.ensure_ready()
    finally:
        vault_db.close()


class _VaultReadProviderRuntime(SecretProviderProtocol):
    """
    Назначение:
        Runtime-обёртка vault read provider c управлением lifecycle SQLite connection.

    Граница:
        Наружу публикуется только `SecretProviderProtocol` + `close()` для composition-root.
    """

    def __init__(self, *, paths_settings: PathsSettings, run_id: str | None) -> None:
        self._vault_db = VaultSqliteDb(cache_dir=paths_settings.cache_dir)
        self._provider = SecretVaultReadService(
            repository=SqliteVaultRepository(self._vault_db),
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
        self._vault_db.close()


class _VaultRetentionRuntime(SecretApplyRetentionHookProtocol):
    """
    Назначение:
        Runtime-обёртка retention/maintenance hooks с lifecycle SQLite connection.
    """

    def __init__(self, *, paths_settings: PathsSettings) -> None:
        self._vault_db = VaultSqliteDb(cache_dir=paths_settings.cache_dir)
        self._service = VaultRetentionService(
            repository=SqliteVaultRepository(self._vault_db),
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
        self._vault_db.close()


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
        - source "vault" -> vault-only `SecretVaultReadService` (без prompt/CSV fallback)
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

    # NOTE: iter_*_ok вынесены наружу через iter_ok(stage_pipeline.run(...))


def build_pipeline_context(
    *,
    dataset_spec: DatasetSpec,
    dataset_name: str,
    cache_roles: SqliteCacheRolePorts,
    pending_settings: PendingSettings,
    observability_settings: ObservabilitySettings,
    catalog: ErrorCatalog,
    csv_has_header: bool,
    secret_store: Any | None = None,
) -> PipelineContext:
    """
    Назначение:
        Единая сборка map/normalize/enrich цепочки.
    """
    enrich_deps = dataset_spec.build_enrich_deps(
        None,
        enrich_lookup=cache_roles.enrich_lookup,
        secret_store=secret_store,
    )
    planning_deps = dataset_spec.build_planning_deps(
        pending_settings,
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
