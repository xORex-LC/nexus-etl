from __future__ import annotations

import sqlite3
from typing import Any

from connector.config.config import Settings
from connector.domain.diagnostics import build_catalog
from connector.domain.ports.secrets import SecretProviderProtocol
from connector.datasets.registry import get_spec, resolve_dataset_name
from connector.datasets.cache_registry import list_cache_specs
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


__all__ = [
    "build_diagnostics_catalog",
    "build_dataset_spec",
    "build_cache",
    "build_identity_repos",
    "build_api_client",
    "build_api_executor",
    "build_api_reader",
    "build_secret_provider",
]
