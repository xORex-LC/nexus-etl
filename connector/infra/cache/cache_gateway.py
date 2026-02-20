from __future__ import annotations

from typing import Iterable

from connector.infra.cache.cache_spec import CacheSpec
from connector.infra.identity.sqlite.identity_repository import SqliteIdentityRepository
from connector.infra.identity.sqlite.pending_links_repository import SqlitePendingLinksRepository
from connector.infra.cache.repository.cache_repository import SqliteCacheRepository
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.sqlite.engine import SqliteEngine


class SqliteCacheGateway:
    """
    Назначение:
        Единый SQLite фасад для cache/identity/pending операций.

    После Block 3:
        - cache_engine (cache.sqlite3) хранит dataset-таблицы (users, organizations…).
        - identity_engine (identity.sqlite3) хранит identity_index, pending_links, identity_runtime_state.
        - Оба движка — унифицированный SqliteEngine из connector.infra.sqlite.
    """

    def __init__(
        self,
        *,
        cache_engine: SqliteEngine,
        identity_engine: SqliteEngine,
        cache_repo: SqliteCacheRepository,
        identity_repo: SqliteIdentityRepository,
        pending_repo: SqlitePendingLinksRepository,
        owns_connection: bool = False,
    ) -> None:
        _ensure_repos_use_correct_engines(cache_engine, identity_engine, cache_repo, identity_repo, pending_repo)
        self._cache_engine = cache_engine
        self._identity_engine = identity_engine
        self._cache_repo = cache_repo
        self._identity_repo = identity_repo
        self._pending_repo = pending_repo
        self._owns_connection = owns_connection
        self._closed = False

    @property
    def engine(self) -> SqliteEngine:
        """Возвращает cache_engine (для совместимости с ролями, которые ожидают engine)."""
        return self._cache_engine

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
    def from_engine(
        cls,
        *,
        cache_engine: SqliteEngine,
        identity_engine: SqliteEngine,
        cache_specs: Iterable[CacheSpec],
        owns_connection: bool = False,
    ) -> "SqliteCacheGateway":
        """
        Назначение:
            Создать шлюз из готовых SqliteEngine.

        Контракт:
            - ensure_cache_ready применяется к cache_engine (dataset-схема).
            - identity_engine уже инициализирован контейнером до вызова (ensure_identity_schema).
        """
        specs = list(cache_specs)
        ensure_cache_ready(cache_engine, specs)
        cache_repo = SqliteCacheRepository(cache_engine, specs)
        identity_repo = SqliteIdentityRepository(identity_engine)
        pending_repo = SqlitePendingLinksRepository(identity_engine)
        return cls(
            cache_engine=cache_engine,
            identity_engine=identity_engine,
            cache_repo=cache_repo,
            identity_repo=identity_repo,
            pending_repo=pending_repo,
            owns_connection=owns_connection,
        )

    def transaction(self):
        return self._cache_engine.transaction()

    def close(self) -> None:
        if self._closed:
            return
        if self._owns_connection:
            self._cache_engine.close()
            self._identity_engine.close()
        self._closed = True

    def __enter__(self) -> "SqliteCacheGateway":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _ensure_repos_use_correct_engines(
    cache_engine: SqliteEngine,
    identity_engine: SqliteEngine,
    cache_repo: SqliteCacheRepository,
    identity_repo: SqliteIdentityRepository,
    pending_repo: SqlitePendingLinksRepository,
) -> None:
    if cache_repo.engine is not cache_engine:
        raise ValueError("cache_repo uses a different engine instance")
    if identity_repo.engine is not identity_engine:
        raise ValueError("identity_repo uses a different engine instance")
    if pending_repo.engine is not identity_engine:
        raise ValueError("pending_repo uses a different engine instance")
