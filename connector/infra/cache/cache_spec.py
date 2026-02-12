from __future__ import annotations

from connector.domain.ports.cache.models import CacheSpec, FieldSpec


SQLITE_TYPE_MAP: dict[str, str] = {
    "string": "TEXT",
    "int": "INTEGER",
    "bool": "INTEGER",
    "float": "REAL",
    "datetime": "TEXT",
    "json": "TEXT",
}


def map_sqlite_type(type_name: str) -> str:
    if type_name not in SQLITE_TYPE_MAP:
        raise ValueError(f"Unsupported cache field type: {type_name}")
    return SQLITE_TYPE_MAP[type_name]
