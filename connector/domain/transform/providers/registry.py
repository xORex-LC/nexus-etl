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
        registry.register_lookup("dictionary.canonicalize", _dictionary_canonicalize)
        registry.register_exists("dictionary.exists_by_key", _dictionary_exists_by_key)
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
    dictionaries = _require_dictionaries(deps, provider_name="dictionary.by_key")
    dict_name, at, fields, limit = _extract_dictionary_lookup_args(
        args,
        provider_name="dictionary.by_key",
    )

    return dictionaries.lookup(
        dict_name,
        str(value),
        at=at,
        fields=fields,
        limit=limit,
    )


def _dictionary_exists_by_key(deps: Any, value: Any, *, args: dict[str, Any]) -> Any | None:
    """
    Exists-provider обязан возвращать row | None (а не bool),
    потому что enrich engine использует `is not None` семантику.
    """
    dictionaries = _require_dictionaries(deps, provider_name="dictionary.exists_by_key")
    dict_name, at, fields, _ = _extract_dictionary_lookup_args(
        args,
        provider_name="dictionary.exists_by_key",
    )
    rows = dictionaries.lookup(
        dict_name,
        str(value),
        at=at,
        fields=fields,
        limit=1,
    )
    return rows[0] if rows else None


def _dictionary_canonicalize(deps: Any, value: Any, *, args: dict[str, Any]) -> list[dict[str, Any]]:
    dictionaries = _require_dictionaries(deps, provider_name="dictionary.canonicalize")
    dict_name, at, limit = _extract_dictionary_canonicalize_args(
        args,
        provider_name="dictionary.canonicalize",
    )
    return dictionaries.canonicalize(
        dict_name,
        str(value),
        at=at,
        limit=limit,
    )


def _require_dictionaries(deps: Any, *, provider_name: str):
    dictionaries = getattr(deps, "dictionaries", None)
    if dictionaries is None:
        raise AttributeError(f"deps.dictionaries is required for provider '{provider_name}'")
    return dictionaries


def _extract_dictionary_lookup_args(
    args: dict[str, Any],
    *,
    provider_name: str,
) -> tuple[str, Any | None, tuple[str, ...] | None, int | None]:
    allowed_args = {"dict_name", "at", "fields", "limit"}
    unknown_args = sorted(set(args) - allowed_args)
    if unknown_args:
        raise ValueError(
            f"Unknown args for provider '{provider_name}': {', '.join(unknown_args)}"
        )

    dict_name = str(args["dict_name"])
    at = args.get("at")

    fields_raw = args.get("fields")
    fields: tuple[str, ...] | None = None
    if fields_raw is not None:
        if not isinstance(fields_raw, (list, tuple)):
            raise TypeError(f"provider '{provider_name}' arg 'fields' must be list/tuple of strings")
        fields = tuple(str(item) for item in fields_raw)

    limit_raw = args.get("limit")
    limit: int | None = None
    if limit_raw is not None:
        limit = int(limit_raw)
        if limit <= 0:
            raise ValueError(f"provider '{provider_name}' arg 'limit' must be > 0")

    return dict_name, at, fields, limit


def _extract_dictionary_canonicalize_args(
    args: dict[str, Any],
    *,
    provider_name: str,
) -> tuple[str, Any | None, int | None]:
    allowed_args = {"dict_name", "at", "limit"}
    unknown_args = sorted(set(args) - allowed_args)
    if unknown_args:
        raise ValueError(
            f"Unknown args for provider '{provider_name}': {', '.join(unknown_args)}"
        )

    dict_name = str(args["dict_name"])
    at = args.get("at")
    limit_raw = args.get("limit")
    limit: int | None = None
    if limit_raw is not None:
        limit = int(limit_raw)
        if limit <= 0:
            raise ValueError(f"provider '{provider_name}' arg 'limit' must be > 0")
    return dict_name, at, limit
