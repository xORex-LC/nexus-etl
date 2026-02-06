"""
Назначение:
    Реестр lookup/exists провайдеров для enrich DSL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


LookupProvider = Callable[[Any, Any], list[dict[str, Any]]]
ExistsProvider = Callable[[Any, Any], Any | None]


@dataclass
class ProviderRegistry:
    """
    Назначение:
        Runtime-реестр провайдеров enrich.
    """

    _lookup: dict[str, LookupProvider] = field(default_factory=dict)
    _exists: dict[str, ExistsProvider] = field(default_factory=dict)

    def register_lookup(self, name: str, provider: LookupProvider) -> None:
        self._lookup[name] = provider

    def register_exists(self, name: str, provider: ExistsProvider) -> None:
        self._exists[name] = provider

    def lookup(self, name: str, deps: Any, value: Any, *, args: dict[str, Any]) -> list[dict[str, Any]]:
        provider = self._lookup.get(name)
        if provider is None:
            raise KeyError(f"Unknown lookup provider: {name}")
        return provider(deps, value, args=args)

    def exists(self, name: str, deps: Any, value: Any, *, args: dict[str, Any]) -> Any | None:
        provider = self._exists.get(name)
        if provider is None:
            raise KeyError(f"Unknown exists provider: {name}")
        return provider(deps, value, args=args)
