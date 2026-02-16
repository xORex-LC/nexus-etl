"""Вспомогательные функции для HTTP-пагинации."""

from __future__ import annotations

from typing import Any


def merge_paging_query(
    *,
    defaults: dict[str, Any] | None,
    overrides: dict[str, Any] | None,
) -> dict[str, Any]:
    """Объединить параметры пагинации и override-параметры."""
    query: dict[str, Any] = dict(defaults or {})
    if overrides:
        query.update(overrides)
    return query
