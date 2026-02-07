"""
Назначение:
    Общие утилиты для стадий transform (не зависят от DSL).
"""

from connector.domain.transform.common.text import (
    normalize_for_compare,
    normalize_text,
)

__all__ = [
    "normalize_for_compare",
    "normalize_text",
]
