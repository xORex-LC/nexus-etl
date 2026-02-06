"""
Назначение:
    Контракты провайдеров lookup/exists для DSL enrich.
"""

from __future__ import annotations

from typing import Any, Protocol


class LookupProviderPort(Protocol):
    """
    Назначение:
        Контракт lookup-провайдера: вернуть кандидаты по значению.
    """

    def lookup(self, deps: Any, value: Any, *, args: dict[str, Any]) -> list[dict[str, Any]]: ...


class ExistsProviderPort(Protocol):
    """
    Назначение:
        Контракт exists-провайдера: вернуть найденную запись или None.
    """

    def exists(self, deps: Any, value: Any, *, args: dict[str, Any]) -> Any | None: ...


__all__ = ["LookupProviderPort", "ExistsProviderPort"]
