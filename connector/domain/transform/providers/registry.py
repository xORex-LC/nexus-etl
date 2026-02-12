"""
Назначение:
    Единый gateway lookup/exists провайдеров для enrich DSL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


LookupProvider = Callable[[Any, Any], list[dict[str, Any]]]
ExistsProvider = Callable[[Any, Any], Any | None]


@dataclass
class ProviderGateway:
    """
    Назначение:
        Runtime-реестр провайдеров enrich.
    """

    _lookup: dict[str, LookupProvider] = field(default_factory=dict)
    _exists: dict[str, ExistsProvider] = field(default_factory=dict)

    @classmethod
    def with_defaults(cls) -> "ProviderGateway":
        """
        Назначение:
            Создать registry c базовыми провайдерами.
        """
        registry = cls()
        registry.register_lookup("cache.by_field", _cache_by_field)
        registry.register_exists("cache.exists_by_field", _cache_exists_by_field)
        registry.register_lookup("dictionary.by_key", _dictionary_by_key)
        return registry

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


def _cache_by_field(deps: Any, value: Any, *, args: dict[str, Any]) -> list[dict[str, Any]]:
    cache_gateway = getattr(deps, "cache_gateway", None)
    if cache_gateway is None:
        raise AttributeError("deps.cache_gateway is required for provider 'cache.by_field'")
    dataset = str(args["dataset"])
    field = str(args["field"])
    include_deleted = bool(args.get("include_deleted", False))
    mode = str(args.get("mode", "exact"))
    return cache_gateway.find(
        dataset,
        {field: value},
        include_deleted=include_deleted,
        mode=mode,
    )


def _cache_exists_by_field(deps: Any, value: Any, *, args: dict[str, Any]) -> Any | None:
    cache_gateway = getattr(deps, "cache_gateway", None)
    if cache_gateway is None:
        raise AttributeError("deps.cache_gateway is required for provider 'cache.exists_by_field'")
    dataset = str(args["dataset"])
    field = str(args["field"])
    include_deleted = bool(args.get("include_deleted", False))
    mode = str(args.get("mode", "exact"))
    return cache_gateway.find_one(
        dataset,
        {field: value},
        include_deleted=include_deleted,
        mode=mode,
    )


def _dictionary_by_key(deps: Any, value: Any, *, args: dict[str, Any]) -> list[dict[str, Any]]:
    dictionaries = getattr(deps, "dictionaries", None)
    if dictionaries is None:
        raise AttributeError("deps.dictionaries is required for provider 'dictionary.by_key'")
    dict_name = str(args["dict_name"])
    at = args.get("at")
    return dictionaries.lookup(dict_name, str(value), at=at)
