from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from typing import Any, Iterable, Iterator

from connector.config.app_settings import (
    ApiSettings,
    DatasetSettings,
    ObservabilitySettings,
    PathsSettings,
    PendingSettings,
)
from connector.domain.diagnostics import build_catalog
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.datasets.registry import get_spec, resolve_dataset_name
from connector.datasets.spec import DatasetSpec
from connector.domain.transform.stages.stages import StagePipeline, MapStage, NormalizeStage, EnrichStage
from connector.domain.transform.resolver.resolve_deps import PlanningDependencies
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.cache.dsl_runtime import CacheDslRuntimeBundle, load_cache_dsl_runtime
from connector.infra.cache.roles import SqliteCacheRolePorts, build_sqlite_cache_role_ports
from connector.infra.http.ankey_client import AnkeyApiClient
from connector.infra.http.request_executor import AnkeyRequestExecutor
from connector.infra.target.legacy.ankey_paged_reader import AnkeyTargetPagedReader
from connector.infra.secrets import NullSecretProvider, PromptSecretProvider, CompositeSecretProvider
from connector.infra.target.factory import (
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


def build_api_client(api_settings: ApiSettings, *, transport: Any | None = None) -> AnkeyApiClient:
    """
    Назначение:
        Создать HTTP клиента к Ankey API без пинга.
    """
    return AnkeyApiClient(
        baseUrl=f"https://{api_settings.host}:{api_settings.port}",
        username=api_settings.username or "",
        password=api_settings.password or "",
        timeoutSeconds=api_settings.timeout_seconds,
        tlsSkipVerify=api_settings.tls_skip_verify,
        caFile=api_settings.ca_file,
        retries=api_settings.retries,
        retryBackoffSeconds=api_settings.retry_backoff_seconds,
        transport=transport,
    )


def build_api_executor(client: AnkeyApiClient) -> AnkeyRequestExecutor:
    """
    Назначение:
        Адаптер для выполнения HTTP запросов.
    """
    return AnkeyRequestExecutor(client)


def build_api_reader(client: AnkeyApiClient) -> AnkeyTargetPagedReader:
    """
    Назначение:
        Reader для чтения страниц из API (cache refresh).
    """
    return AnkeyTargetPagedReader(client)


def build_secret_provider(source: str | None, vault_file: str | None) -> SecretProviderProtocol:
    """
    Назначение:
        Фабрика провайдера секретов.
    Контракт:
        - source None/"none" -> NullSecretProvider
        - source "prompt" -> PromptSecretProvider
        - source "vault" -> Composite(FileVault -> Prompt)
        - любое другое значение: NullSecretProvider
    """
    if not source or source == "none":
        return NullSecretProvider()
    if source == "prompt":
        return PromptSecretProvider()
    if source == "vault":
        if not vault_file:
            return PromptSecretProvider()
        from connector.infra.secrets import FileVaultSecretProvider

        return CompositeSecretProvider([FileVaultSecretProvider(vault_file), PromptSecretProvider()])
    return NullSecretProvider()


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
    "build_api_client",
    "build_api_executor",
    "build_api_reader",
    "build_target_runtime",
    "build_target_runtime_with_info",
    "build_secret_provider",
    "PipelineContext",
    "build_pipeline_context",
]
