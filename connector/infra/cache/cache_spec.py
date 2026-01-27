from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FieldSpec:
    name: str
    type: str
    nullable: bool = True
    source: str | None = None


@dataclass(frozen=True)
class CacheSpec:
    dataset: str
    table: str
    primary_key: tuple[str, ...]
    fields: tuple[FieldSpec, ...]
    unique_indexes: tuple[tuple[str, ...], ...] = ()
    indexes: tuple[tuple[str, ...], ...] = ()


SQLITE_TYPE_MAP: dict[str, str] = {
    "string": "TEXT",
    "int": "INTEGER",
    "bool": "INTEGER",
    "float": "REAL",
    "datetime": "TEXT",
}


def map_sqlite_type(type_name: str) -> str:
    if type_name not in SQLITE_TYPE_MAP:
        raise ValueError(f"Unsupported cache field type: {type_name}")
    return SQLITE_TYPE_MAP[type_name]
