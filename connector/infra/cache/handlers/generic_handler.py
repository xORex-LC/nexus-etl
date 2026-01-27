from __future__ import annotations

from connector.domain.ports.cache_repository import UpsertResult
from connector.infra.cache.cache_spec import CacheSpec, FieldSpec, map_sqlite_type
from connector.infra.cache.handlers.base import CacheDatasetHandler
from connector.infra.cache.sqlite_engine import SqliteEngine


class GenericCacheHandler(CacheDatasetHandler):
    """
    Назначение/ответственность:
        Универсальный handler для кэша на основе CacheSpec.
    """

    def __init__(self, spec: CacheSpec) -> None:
        self.spec = spec
        self.dataset = spec.dataset
        self.table_names = (spec.table,)

    def ensure_schema(self, engine: SqliteEngine) -> None:
        columns_sql = []
        field_names = {field.name for field in self.spec.fields}
        for field in self.spec.fields:
            col_type = map_sqlite_type(field.type)
            not_null = " NOT NULL" if not field.nullable else ""
            columns_sql.append(f"{field.name} {col_type}{not_null}")

        pk = self.spec.primary_key
        for key in pk:
            if key not in field_names:
                raise ValueError(f"Primary key field '{key}' is missing in cache spec for {self.dataset}")
        pk_clause = f", PRIMARY KEY ({', '.join(pk)})" if pk else ""

        engine.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {self.spec.table} (
                {', '.join(columns_sql)}{pk_clause}
            )
            """
        )

        for columns in self.spec.unique_indexes:
            index_name = _index_name(self.spec.table, columns, unique=True)
            engine.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {self.spec.table}({', '.join(columns)})"
            )
        for columns in self.spec.indexes:
            index_name = _index_name(self.spec.table, columns, unique=False)
            engine.execute(
                f"CREATE INDEX IF NOT EXISTS {index_name} ON {self.spec.table}({', '.join(columns)})"
            )

    def upsert(self, engine: SqliteEngine, write_model: dict) -> UpsertResult:
        values = _extract_values(self.spec.fields, write_model)
        _validate_required(self.spec.fields, values, self.dataset)

        pk = self.spec.primary_key
        if not pk:
            raise ValueError(f"Primary key is required for cache spec {self.dataset}")
        pk_clause = " AND ".join(f"{key} = :{key}" for key in pk)
        existing = engine.fetchone(f"SELECT 1 FROM {self.spec.table} WHERE {pk_clause}", values)

        if existing:
            update_fields = [field.name for field in self.spec.fields if field.name not in pk]
            if update_fields:
                set_clause = ", ".join(f"{name} = :{name}" for name in update_fields)
                engine.execute(
                    f"UPDATE {self.spec.table} SET {set_clause} WHERE {pk_clause}",
                    values,
                )
            return UpsertResult.UPDATED

        columns = ", ".join(values.keys())
        placeholders = ", ".join(f":{name}" for name in values.keys())
        engine.execute(
            f"INSERT INTO {self.spec.table}({columns}) VALUES({placeholders})",
            values,
        )
        return UpsertResult.INSERTED

    def count_total(self, engine: SqliteEngine) -> int:
        row = engine.fetchone(f"SELECT COUNT(*) FROM {self.spec.table}")
        return int(row[0]) if row else 0

    def count_by_table(self, engine: SqliteEngine) -> dict[str, int]:
        return {self.spec.table: self.count_total(engine)}

    def clear(self, engine: SqliteEngine) -> None:
        engine.execute(f"DELETE FROM {self.spec.table}")


def _index_name(table: str, columns: tuple[str, ...], *, unique: bool) -> str:
    prefix = "uidx" if unique else "idx"
    return f"{prefix}_{table}_{'_'.join(columns)}"


def _extract_values(fields: tuple[FieldSpec, ...], write_model: dict) -> dict:
    values: dict[str, object] = {}
    for field in fields:
        source = field.source or field.name
        raw = write_model.get(source)
        if field.type == "bool" and raw is not None:
            if isinstance(raw, bool):
                raw = 1 if raw else 0
            elif isinstance(raw, int):
                raw = 1 if raw != 0 else 0
        values[field.name] = raw
    return values


def _validate_required(fields: tuple[FieldSpec, ...], values: dict, dataset: str) -> None:
    for field in fields:
        if field.nullable:
            continue
        value = values.get(field.name)
        if value is None:
            raise ValueError(f"Missing required cache field: {field.name} (dataset={dataset})")
        if isinstance(value, str) and value.strip() == "":
            raise ValueError(f"Missing required cache field: {field.name} (dataset={dataset})")
