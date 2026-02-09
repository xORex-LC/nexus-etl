from __future__ import annotations

from typing import Iterable

from connector.infra.cache.cache_spec import CacheSpec
from connector.infra.cache.gateway import SqliteCacheGateway
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
    return SqliteCacheGateway(
        engine=engine,
        cache_specs=list(cache_specs),
    )
