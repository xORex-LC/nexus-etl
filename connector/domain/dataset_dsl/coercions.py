"""
Назначение:
    Type coercion функции для SinkSpec-driven payload building.

Граница ответственности:
    - Owns: конвертация значений по типам SinkFieldSpec (bool, int, float, string).
    - Does NOT: валидация required/nullable (это ответственность payload_compiler).
"""

from __future__ import annotations

from typing import Any


def to_int_or_none(value: Any) -> int | None:
    """Преобразовать значение в int или None для nullable numeric полей."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("bool is not valid for integer field")
    if isinstance(value, str):
        return int(value.strip())
    return int(value)


def to_bool(value: Any) -> bool:
    """Преобразовать значение в bool по правилам payload-контракта."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "y"):
            return True
        if normalized in ("0", "false", "no", "n"):
            return False
    raise ValueError(f"Invalid boolean value: {value!r}")


def to_float_or_none(value: Any) -> float | None:
    """Преобразовать значение в float или None для nullable numeric полей."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("bool is not valid for float field")
    if isinstance(value, str):
        return float(value.strip())
    return float(value)
