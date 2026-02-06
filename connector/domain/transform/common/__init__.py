"""
Назначение:
    Общие утилиты для стадий transform (не зависят от DSL).
"""

from connector.domain.transform.common.text import normalize_text, normalize_whitespace

__all__ = [
    "normalize_text",
    "normalize_whitespace",
]
