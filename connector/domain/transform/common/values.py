"""
Назначение:
    Общие утилиты работы со значениями для стадий transform.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Mapping


def read_field_value(payload: Any, field_name: str) -> Any:
    """
    Назначение:
        Унифицированно прочитать плоское поле из dict/object payload.

    Граница ответственности:
        - Owns: чтение runtime-row/object значений без знания о DSL-правилах.
        - Does NOT: применять fallback/precedence между разными источниками данных.
    """
    if isinstance(payload, Mapping):
        return payload.get(field_name)
    if payload is None:
        return None
    return getattr(payload, field_name, None)


def read_value(
    *,
    record_values: Mapping[str, Any] | None,
    row_values: Mapping[str, Any] | None,
    path: str,
) -> Any:
    """
    Назначение:
        Унифицированное чтение значений из record/row.
    """
    if path.startswith("row."):
        key = path.split("row.", 1)[1]
        return None if row_values is None else row_values.get(key)
    if path.startswith("record."):
        key = path.split("record.", 1)[1]
        return None if record_values is None else record_values.get(key)
    if record_values and path in record_values:
        return record_values.get(path)
    if row_values and path in row_values:
        return row_values.get(path)
    return None


def read_value_path(obj: Any, path: str | None) -> Any:
    """
    Назначение:
        Доступ к вложенным значениям через "a.b.c".
    """
    if path is None:
        return None
    current = obj
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, Mapping):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current


def to_mapping(value: Any) -> Mapping[str, Any] | None:
    """
    Назначение:
        Привести объект/датакласс к Mapping.
    """
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value):
        return asdict(value)
    return value.__dict__
