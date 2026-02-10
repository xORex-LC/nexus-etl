from __future__ import annotations

from typing import Iterable

from connector.infra.cache.cache_spec import CacheSpec
from connector.infra.cache.gateway import SqliteCacheGateway
from connector.infra.cache.identity_repository import SqliteIdentityRepository
from connector.infra.cache.pending_links_repository import SqlitePendingLinksRepository
from connector.infra.cache.repository import SqliteCacheRepository
from connector.infra.cache.sqlite_engine import SqliteEngine


def build_sqlite_cache_gateway(
    *,
    engine: SqliteEngine,
    cache_specs: Iterable[CacheSpec],
) -> SqliteCacheGateway:
    """
    Назначение:
        Единая фабрика сборки SQLite cache gateway.
    """
    cache_repo = SqliteCacheRepository(engine, list(cache_specs))
    identity_repo = SqliteIdentityRepository(engine)
    pending_repo = SqlitePendingLinksRepository(engine)
    return SqliteCacheGateway(
        cache_repo=cache_repo,
        identity_repo=identity_repo,
        pending_repo=pending_repo,
    )

