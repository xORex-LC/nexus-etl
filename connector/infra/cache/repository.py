from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from connector.domain.ports.cache_repository import CacheMeta, CacheRepositoryProtocol, UpsertResult
from connector.infra.cache.cache_spec import CacheSpec
from connector.infra.cache.handlers.generic_handler import GenericCacheHandler
from connector.infra.cache.sqlite_engine import SqliteEngine


class SqliteCacheRepository(CacheRepositoryProtocol):
    """
    Назначение/ответственность:
        Реализация репозитория кэша на SQLite.
    """

    def __init__(self, engine: SqliteEngine, cache_specs: list[CacheSpec]):
        self.engine = engine
        self._handlers = _build_handlers(cache_specs)

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.engine.transaction():
            yield

    def upsert(self, dataset: str, write_model: dict) -> UpsertResult:
        handler = _get_handler(self._handlers, dataset)
        return handler.upsert(self.engine, write_model)

    def count(self, dataset: str) -> int:
        handler = _get_handler(self._handlers, dataset)
        return handler.count_total(self.engine)

    def count_by_table(self, dataset: str) -> dict[str, int]:
        handler = _get_handler(self._handlers, dataset)
        return handler.count_by_table(self.engine)

    def clear(self, dataset: str) -> None:
        handler = _get_handler(self._handlers, dataset)
        handler.clear(self.engine)

    def list_datasets(self) -> list[str]:
        return list(self._handlers.keys())

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

    def reset_meta(self, dataset: str) -> None:
        self.engine.execute("DELETE FROM meta WHERE key LIKE ?", (f"{dataset}.%",))

    def find(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> list[dict]:
        handler = _get_handler(self._handlers, dataset)
        spec = getattr(handler, "spec", None)
        if spec is None:
            raise ValueError(f"Cache handler for dataset '{dataset}' does not expose spec")

        field_map = _build_field_map(spec.fields)
        if not filters:
            raise ValueError("find() requires at least one filter")

        where_parts: list[str] = []
        params: list[Any] = []

        for key, value in filters.items():
            if key not in field_map:
                raise ValueError(f"Unknown cache field '{key}' for dataset '{dataset}'")
            field_name = field_map[key]
            clause, clause_params = _build_clause(field_name, value, mode)
            if clause is None:
                return []
            where_parts.append(clause)
            params.extend(clause_params)

        if not include_deleted and "deletion_date" in field_map:
            where_parts.append("deletion_date IS NULL")

        where_sql = " AND ".join(where_parts) if where_parts else "1=1"
        rows = self.engine.fetchall(f"SELECT * FROM {spec.table} WHERE {where_sql}", tuple(params))
        return _rows_to_dicts(rows)

    def find_one(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> dict | None:
        results = self.find(dataset, filters, include_deleted=include_deleted, mode=mode)
        return results[0] if results else None


def _build_handlers(cache_specs: list[CacheSpec]) -> dict[str, GenericCacheHandler]:
    handlers: dict[str, GenericCacheHandler] = {}
    for spec in cache_specs:
        if spec.dataset in handlers:
            raise ValueError(f"Duplicate cache spec for dataset: {spec.dataset}")
        handlers[spec.dataset] = GenericCacheHandler(spec)
    return handlers


def _get_handler(handlers: dict[str, GenericCacheHandler], dataset: str) -> GenericCacheHandler:
    if dataset not in handlers:
        raise ValueError(f"Unsupported cache dataset: {dataset}")
    return handlers[dataset]


def _rows_to_dicts(rows: list[Any]) -> list[dict]:
    result: list[dict] = []
    for row in rows:
        if row is None:
            continue
        if hasattr(row, "keys"):
            result.append({k: row[k] for k in row.keys()})
        else:
            result.append(dict(row))
    return result


def _build_field_map(fields) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for field in fields:
        mapping[field.name] = field.name
        if field.source:
            mapping[field.source] = field.name
    return mapping


def _build_clause(field_name: str, value: Any, mode: str) -> tuple[str | None, list[Any]]:
    if mode == "exact":
        return f"{field_name} = ?", [value]
    if mode == "like":
        return f"{field_name} LIKE ?", [value]
    if mode == "in":
        if value is None:
            return None, []
        if isinstance(value, (list, tuple, set)):
            value_list = list(value)
        else:
            value_list = [value]
        if not value_list:
            return None, []
        placeholders = ", ".join("?" for _ in value_list)
        return f"{field_name} IN ({placeholders})", value_list
    raise ValueError(f"Unsupported search mode: {mode}")
