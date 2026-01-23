from __future__ import annotations

from typing import Protocol

from connector.domain.ports.cache_repository import UpsertResult
from connector.infra.cache.sqlite_engine import SqliteEngine


class CacheDatasetHandler(Protocol):
    """
    Назначение/ответственность:
        Датасет-специфичный обработчик хранения в кэше.
    """

    dataset: str
    table_names: tuple[str, ...]

    def ensure_schema(self, engine: SqliteEngine) -> None: ...
    def upsert(self, engine: SqliteEngine, write_model: dict) -> UpsertResult: ...
    def count_total(self, engine: SqliteEngine) -> int: ...
    def count_by_table(self, engine: SqliteEngine) -> dict[str, int]: ...
    def clear(self, engine: SqliteEngine) -> None: ...
