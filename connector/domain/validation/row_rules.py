from __future__ import annotations

import re
from typing import Any

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

__all__ = [
    "normalize_whitespace",
    "validate_email",
    "parse_boolean_strict",
    "parse_int_strict",
    "_boolean_parser",
]

def normalize_whitespace(value: str | None) -> str | None:
    """
    Назначение:
        Нормализует пробелы в строке.
    """
    if value is None:
        return None
    return " ".join(value.split())

def validate_email(value: str) -> bool:
    return EMAIL_RE.match(value) is not None

def parse_boolean_strict(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("Invalid boolean value")

def parse_int_strict(value: str) -> int:
    if value.strip() == "":
        raise ValueError("Empty int value")
    return int(value)

def _boolean_parser(value: Any, add_error, _add_warning) -> bool | None:
    try:
        return parse_boolean_strict(str(value))
    except ValueError:
        add_error(
            code="INVALID_BOOLEAN",
            field="isLogonDisable",
            message="isLogonDisable must be 'true' or 'false'",
        )
        return None
