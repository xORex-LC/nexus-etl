from __future__ import annotations


from connector.domain.ports.cache_repository import UpsertResult
from connector.infra.cache.sqlite_engine import SqliteEngine


class CacheDatasetHandler:
    """
    Назначение/ответственность:
        Датасет-специфичный обработчик хранения в кэше.
    """

    dataset: str
    table_names: tuple[str, ...]

    def ensure_schema(self, engine: SqliteEngine) -> None:
        raise NotImplementedError

    def upsert(self, engine: SqliteEngine, write_model: dict) -> UpsertResult:
        raise NotImplementedError

    def count_total(self, engine: SqliteEngine) -> int:
        raise NotImplementedError

    def count_by_table(self, engine: SqliteEngine) -> dict[str, int]:
        raise NotImplementedError

    def clear(self, engine: SqliteEngine) -> None:
        raise NotImplementedError
