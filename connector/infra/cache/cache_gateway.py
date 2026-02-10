from __future__ import annotations

from typing import Iterable

from connector.config.config import Settings
from connector.infra.cache.cache_spec import CacheSpec
from connector.infra.cache.backends.sqlite.db import getCacheDbPath, openCacheDb
from connector.infra.cache.repository.identity_repository import SqliteIdentityRepository
from connector.infra.cache.repository.pending_links_repository import SqlitePendingLinksRepository
from connector.infra.cache.repository.cache_repository import SqliteCacheRepository
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.cache.backends.sqlite.engine import SqliteEngine


class SqliteCacheGateway:
    """
    Назначение:
        Единый SQLite фасад для cache/identity/pending операций.
    """

    def __init__(
        self,
        *,
        engine: SqliteEngine,
        cache_repo: SqliteCacheRepository,
        identity_repo: SqliteIdentityRepository,
        pending_repo: SqlitePendingLinksRepository,
        owns_connection: bool = False,
    ) -> None:
        _ensure_same_engine(engine, cache_repo, identity_repo, pending_repo)
        self._engine = engine
        self._cache_repo = cache_repo
        self._identity_repo = identity_repo
        self._pending_repo = pending_repo
        self._owns_connection = owns_connection
        self._closed = False

    @property
    def engine(self) -> SqliteEngine:
        return self._engine

    @property
    def connection(self):
        return self._engine.conn

    @property
    def cache(self) -> SqliteCacheRepository:
        return self._cache_repo

    @property
    def identity(self) -> SqliteIdentityRepository:
        return self._identity_repo

    @property
    def pending(self) -> SqlitePendingLinksRepository:
        return self._pending_repo

    @classmethod
    def open(
        cls,
        *,
        settings: Settings,
        cache_specs: Iterable[CacheSpec],
    ) -> "SqliteCacheGateway":
        db_path = getCacheDbPath(settings.cache_dir)
        conn = openCacheDb(db_path)
        engine = SqliteEngine(conn)
        return cls.from_engine(
            engine=engine,
            cache_specs=cache_specs,
            owns_connection=True,
        )

    @classmethod
    def from_engine(
        cls,
        *,
        engine: SqliteEngine,
        cache_specs: Iterable[CacheSpec],
        owns_connection: bool = False,
    ) -> "SqliteCacheGateway":
        specs = list(cache_specs)
        ensure_cache_ready(engine, specs)
        cache_repo = SqliteCacheRepository(engine, specs)
        identity_repo = SqliteIdentityRepository(engine)
        pending_repo = SqlitePendingLinksRepository(engine)
        return cls(
            engine=engine,
            cache_repo=cache_repo,
            identity_repo=identity_repo,
            pending_repo=pending_repo,
            owns_connection=owns_connection,
        )

    def transaction(self):
        return self._engine.transaction()

    def close(self) -> None:
        if self._closed:
            return
        if self._owns_connection:
            self._engine.conn.close()
        self._closed = True

    def __enter__(self) -> "SqliteCacheGateway":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _ensure_same_engine(
    engine: SqliteEngine,
    cache_repo: SqliteCacheRepository,
    identity_repo: SqliteIdentityRepository,
    pending_repo: SqlitePendingLinksRepository,
) -> None:
    if cache_repo.engine is not engine:
        raise ValueError("cache_repo uses a different engine instance")
    if identity_repo.engine is not engine:
        raise ValueError("identity_repo uses a different engine instance")
    if pending_repo.engine is not engine:
        raise ValueError("pending_repo uses a different engine instance")
