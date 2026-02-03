from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Iterable

from connector.config.config import Settings
from connector.domain.diagnostics import build_catalog
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.secrets import SecretProviderProtocol
from connector.datasets.registry import get_spec, resolve_dataset_name
from connector.datasets.cache_registry import list_cache_specs
from connector.datasets.spec import DatasetSpec, ValidationBundle
from connector.domain.transform.pipeline import TransformPipeline
from connector.domain.transform.result import TransformResult
from connector.domain.validation.validator import Validator
from connector.domain.planning.deps import PlanningDependencies
from connector.usecases.enrich_usecase import EnrichUseCase
from connector.usecases.validate_usecase import ValidateUseCase
from connector.infra.cache.db import getCacheDbPath, openCacheDb
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.cache.repository import SqliteCacheRepository
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


def build_cache(settings: Settings) -> tuple[sqlite3.Connection, SqliteEngine, SqliteCacheRepository, list[Any]]:
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
    return conn, engine, cache_repo, cache_specs


def build_identity_repos(engine: SqliteEngine) -> tuple[SqliteIdentityRepository, SqlitePendingLinksRepository]:
    """
    Назначение:
        Репозитории для identity/pending_links (используются apply/resolve).
    """
    return SqliteIdentityRepository(engine), SqlitePendingLinksRepository(engine)


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
        Используется как единый источник для map/normalize/enrich/validate.
    """

    dataset_name: str
    catalog: ErrorCatalog
    row_source: Iterable
    transformer: TransformPipeline
    validator: Validator
    planning_deps: PlanningDependencies
    report_items_limit: int

    def iter_enriched_ok(self) -> Iterable[TransformResult]:
        enrich_uc = EnrichUseCase(
            report_items_limit=self.report_items_limit,
            include_enriched_items=False,
        )
        return enrich_uc.iter_enriched_ok(
            row_source=self.row_source,
            transformer=self.transformer,
            catalog=self.catalog,
        )

    def iter_validated_ok(self) -> Iterable[TransformResult]:
        validate_uc = ValidateUseCase(
            report_items_limit=self.report_items_limit,
            include_valid_items=False,
        )
        return validate_uc.iter_validated_ok(
            enriched_source=self.iter_enriched_ok(),
            validator=self.validator,
            catalog=self.catalog,
        )


def build_pipeline_context(
    *,
    dataset_spec: DatasetSpec,
    dataset_name: str,
    conn,
    settings: Settings,
    catalog: ErrorCatalog,
    csv_path: str,
    csv_has_header: bool,
    secret_store: Any | None = None,
) -> PipelineContext:
    """
    Назначение:
        Единая сборка map/normalize/enrich/validate цепочки.
    """
    validation_deps = dataset_spec.build_validation_deps(conn, settings)
    enrich_deps = dataset_spec.build_enrich_deps(conn, settings, secret_store=secret_store)
    planning_deps = dataset_spec.build_planning_deps(conn, settings)

    transformer = dataset_spec.build_pipeline(validation_deps, enrich_deps, catalog)

    validation_bundle: ValidationBundle = dataset_spec.build_validator(validation_deps, catalog)
    validator = validation_bundle.validator

    row_source = dataset_spec.build_record_source(csv_path=csv_path, csv_has_header=csv_has_header)

    return PipelineContext(
        dataset_name=dataset_name,
        catalog=catalog,
        row_source=row_source,
        transformer=transformer,
        validator=validator,
        planning_deps=planning_deps,
        report_items_limit=settings.report_items_limit,
    )


__all__ = [
    "build_diagnostics_catalog",
    "build_dataset_spec",
    "build_cache",
    "build_identity_repos",
    "build_api_client",
    "build_api_executor",
    "build_api_reader",
    "build_secret_provider",
    "PipelineContext",
    "build_pipeline_context",
]
