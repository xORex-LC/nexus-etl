from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from connector.config.config import Settings
from connector.domain.diagnostics import build_catalog
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.datasets.registry import get_spec, resolve_dataset_name
from connector.datasets.cache_registry import list_cache_specs
from connector.datasets.spec import DatasetSpec
from connector.domain.transform.stages.stages import StagePipeline, MapStage, NormalizeStage, EnrichStage
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.resolver.resolve_deps import PlanningDependencies
from connector.infra.cache.db import getCacheDbPath, openCacheDb
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.cache.repository import SqliteCacheRepository
from connector.infra.cache.gateway import SqliteCacheGateway
from connector.infra.cache.identity_repository import SqliteIdentityRepository
from connector.infra.cache.pending_links_repository import SqlitePendingLinksRepository
from connector.infra.http.ankey_client import AnkeyApiClient
from connector.infra.http.request_executor import AnkeyRequestExecutor
from connector.infra.target.ankey_gateway import AnkeyTargetPagedReader
from connector.infra.secrets import NullSecretProvider, PromptSecretProvider, CompositeSecretProvider


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
    settings: Settings,
    *,
    secrets: SecretProviderProtocol | None = None,
):
    """
    Назначение:
        Разрешить имя датасета и вернуть соответствующий DatasetSpec.
    """
    dataset_name = resolve_dataset_name(dataset, settings.dataset_name)
    return dataset_name, get_spec(dataset_name, secrets=secrets)


def build_cache(settings: Settings) -> tuple[sqlite3.Connection, SqliteEngine, SqliteCacheGateway, list[Any]]:
    """
    Назначение:
        Сконфигурировать cache-хранилище (sqlite) и репозиторий.
    """
    cache_db_path = getCacheDbPath(settings.cache_dir)
    conn = openCacheDb(cache_db_path)
    engine = SqliteEngine(conn)
    cache_specs = list_cache_specs()
    ensure_cache_ready(engine, cache_specs)
    cache_repo = SqliteCacheRepository(engine, cache_specs)
    identity_repo = SqliteIdentityRepository(engine)
    pending_repo = SqlitePendingLinksRepository(engine)
    gateway = SqliteCacheGateway(
        cache_repo=cache_repo,
        identity_repo=identity_repo,
        pending_repo=pending_repo,
    )
    return conn, engine, gateway, cache_specs


def build_api_client(settings: Settings, *, transport: Any | None = None) -> AnkeyApiClient:
    """
    Назначение:
        Создать HTTP клиента к Ankey API без пинга.
    """
    return AnkeyApiClient(
        baseUrl=f"https://{settings.host}:{settings.port}",
        username=settings.api_username or "",
        password=settings.api_password or "",
        timeoutSeconds=settings.timeout_seconds,
        tlsSkipVerify=settings.tls_skip_verify,
        caFile=settings.ca_file,
        retries=settings.retries,
        retryBackoffSeconds=settings.retry_backoff_seconds,
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
    conn,
    settings: Settings,
    catalog: ErrorCatalog,
    csv_has_header: bool,
    secret_store: Any | None = None,
) -> PipelineContext:
    """
    Назначение:
        Единая сборка map/normalize/enrich цепочки.
    """
    cache_gateway = _build_cache_gateway_for_dataset(conn, dataset_spec)
    enrich_deps = dataset_spec.build_enrich_deps(
        settings,
        cache_gateway=cache_gateway,
        secret_store=secret_store,
    )
    planning_deps = dataset_spec.build_planning_deps(
        settings,
        cache_gateway=cache_gateway,
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
        report_items_limit=settings.report_items_limit,
    )


def _build_cache_gateway_for_dataset(conn, dataset_spec: DatasetSpec) -> SqliteCacheGateway:
    """
    Назначение:
        Построить единый cache gateway из sqlite-соединения и cache-specs датасета.
    """
    engine = SqliteEngine(conn)
    cache_repo = SqliteCacheRepository(engine, dataset_spec.build_cache_specs())
    identity_repo = SqliteIdentityRepository(engine)
    pending_repo = SqlitePendingLinksRepository(engine)
    return SqliteCacheGateway(
        cache_repo=cache_repo,
        identity_repo=identity_repo,
        pending_repo=pending_repo,
    )


__all__ = [
    "build_diagnostics_catalog",
    "build_dataset_spec",
    "build_cache",
    "build_api_client",
    "build_api_executor",
    "build_api_reader",
    "build_secret_provider",
    "PipelineContext",
    "build_pipeline_context",
]
