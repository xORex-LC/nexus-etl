from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from connector.domain.ports.cache_repository import CacheMeta, CacheRepositoryProtocol, UpsertResult
from connector.infra.cache.handlers.registry import CacheHandlerRegistry
from connector.infra.cache.sqlite_engine import SqliteEngine


class SqliteCacheRepository(CacheRepositoryProtocol):
    """
    Назначение/ответственность:
        Реализация репозитория кэша на SQLite.
    """

    def __init__(self, engine: SqliteEngine, registry: CacheHandlerRegistry):
        self.engine = engine
        self.registry = registry

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.engine.transaction():
            yield

    def upsert(self, dataset: str, write_model: dict) -> UpsertResult:
        handler = self.registry.get(dataset)
        return handler.upsert(self.engine, write_model)

    def count(self, dataset: str) -> int:
        handler = self.registry.get(dataset)
        return handler.count_total(self.engine)

    def count_by_table(self, dataset: str) -> dict[str, int]:
        handler = self.registry.get(dataset)
        return handler.count_by_table(self.engine)

    def clear(self, dataset: str) -> None:
        handler = self.registry.get(dataset)
        handler.clear(self.engine)

    def get_meta(self, dataset: str | None = None) -> CacheMeta:
        if dataset is None:
            rows = self.engine.fetchall("SELECT key, value FROM meta")
            return CacheMeta({row[0]: row[1] for row in rows})
        rows = self.engine.fetchall("SELECT key, value FROM meta WHERE key LIKE ?", (f"{dataset}.%",))
        values: dict[str, str | None] = {}
        for row in rows:
            key = row[0].split(".", 1)[1] if "." in row[0] else row[0]
            values[key] = row[1]
        return CacheMeta(values)

    def set_meta(self, dataset: str | None, key: str, value: str | None) -> None:
        full_key = key if dataset is None else f"{dataset}.{key}"
        if value is None:
            self.engine.execute("DELETE FROM meta WHERE key = ?", (full_key,))
            return
        self.engine.execute(
            """
            INSERT INTO meta(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (full_key, value),
        )
