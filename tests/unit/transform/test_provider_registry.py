from __future__ import annotations

from dataclasses import dataclass

import pytest

from connector.domain.transform.providers.registry import ProviderGateway


@dataclass
class _DummyDictionaryProvider:
    lookup_calls: list[dict]
    canonicalize_calls: list[dict]
    lookup_result: list[dict]
    canonicalize_result: list[dict]

    def lookup(
        self,
        dict_name: str,
        key: str,
        at=None,
        fields=None,
        limit=None,
    ) -> list[dict]:
        self.lookup_calls.append(
            {
                "dict_name": dict_name,
                "key": key,
                "at": at,
                "fields": fields,
                "limit": limit,
            }
        )
        return list(self.lookup_result)

    def canonicalize(
        self,
        dict_name: str,
        value: str,
        at=None,
        limit=None,
    ) -> list[dict]:
        self.canonicalize_calls.append(
            {
                "dict_name": dict_name,
                "value": value,
                "at": at,
                "limit": limit,
            }
        )
        return list(self.canonicalize_result)


@dataclass
class _DummyDeps:
    dictionaries: _DummyDictionaryProvider


def test_dictionary_provider_passes_fields_and_limit() -> None:
    provider = _DummyDictionaryProvider(
        lookup_calls=[],
        canonicalize_calls=[],
        lookup_result=[{"ok": True}],
        canonicalize_result=[],
    )
    deps = _DummyDeps(dictionaries=provider)
    gateway = ProviderGateway.with_defaults()

    result = gateway.lookup(
        "dictionary.by_key",
        deps,
        "user-1",
        args={"dict_name": "organizations", "at": "2026-02-20", "fields": ["name", "ouid"], "limit": 2},
    )

    assert result == [{"ok": True}]
    assert provider.lookup_calls == [
        {
            "dict_name": "organizations",
            "key": "user-1",
            "at": "2026-02-20",
            "fields": ("name", "ouid"),
            "limit": 2,
        }
    ]


def test_dictionary_provider_without_optional_args() -> None:
    provider = _DummyDictionaryProvider(
        lookup_calls=[],
        canonicalize_calls=[],
        lookup_result=[{"ok": True}],
        canonicalize_result=[],
    )
    deps = _DummyDeps(dictionaries=provider)
    gateway = ProviderGateway.with_defaults()

    gateway.lookup("dictionary.by_key", deps, "user-1", args={"dict_name": "organizations"})

    assert provider.lookup_calls[0]["fields"] is None
    assert provider.lookup_calls[0]["limit"] is None


def test_dictionary_provider_rejects_unknown_args() -> None:
    provider = _DummyDictionaryProvider(
        lookup_calls=[],
        canonicalize_calls=[],
        lookup_result=[],
        canonicalize_result=[],
    )
    deps = _DummyDeps(dictionaries=provider)
    gateway = ProviderGateway.with_defaults()

    with pytest.raises(ValueError, match="Unknown args"):
        gateway.lookup(
            "dictionary.by_key",
            deps,
            "user-1",
            args={"dict_name": "organizations", "unexpected": True},
        )


def test_dictionary_provider_rejects_invalid_fields_type() -> None:
    provider = _DummyDictionaryProvider(
        lookup_calls=[],
        canonicalize_calls=[],
        lookup_result=[],
        canonicalize_result=[],
    )
    deps = _DummyDeps(dictionaries=provider)
    gateway = ProviderGateway.with_defaults()

    with pytest.raises(TypeError, match="must be list/tuple"):
        gateway.lookup(
            "dictionary.by_key",
            deps,
            "user-1",
            args={"dict_name": "organizations", "fields": "name"},
        )


@pytest.mark.parametrize("bad_limit", [0, -1, -100])
def test_dictionary_provider_rejects_non_positive_limit(bad_limit: int) -> None:
    provider = _DummyDictionaryProvider(
        lookup_calls=[],
        canonicalize_calls=[],
        lookup_result=[],
        canonicalize_result=[],
    )
    deps = _DummyDeps(dictionaries=provider)
    gateway = ProviderGateway.with_defaults()

    with pytest.raises(ValueError, match="must be > 0"):
        gateway.lookup(
            "dictionary.by_key",
            deps,
            "user-1",
            args={"dict_name": "organizations", "limit": bad_limit},
        )


def test_dictionary_exists_by_key_returns_first_row() -> None:
    provider = _DummyDictionaryProvider(
        lookup_calls=[],
        canonicalize_calls=[],
        lookup_result=[{"id": "r1"}, {"id": "r2"}],
        canonicalize_result=[],
    )
    deps = _DummyDeps(dictionaries=provider)
    gateway = ProviderGateway.with_defaults()

    result = gateway.exists(
        "dictionary.exists_by_key",
        deps,
        "user-1",
        args={"dict_name": "organizations", "fields": ["id"]},
    )

    assert result == {"id": "r1"}
    assert provider.lookup_calls[0]["limit"] == 1
    assert provider.lookup_calls[0]["fields"] == ("id",)


def test_dictionary_exists_by_key_returns_none_on_miss() -> None:
    provider = _DummyDictionaryProvider(
        lookup_calls=[],
        canonicalize_calls=[],
        lookup_result=[],
        canonicalize_result=[],
    )
    deps = _DummyDeps(dictionaries=provider)
    gateway = ProviderGateway.with_defaults()

    result = gateway.exists(
        "dictionary.exists_by_key",
        deps,
        "user-1",
        args={"dict_name": "organizations"},
    )

    assert result is None
    assert provider.lookup_calls[0]["limit"] == 1


def test_dictionary_canonicalize_lookup_provider_passes_args() -> None:
    provider = _DummyDictionaryProvider(
        lookup_calls=[],
        canonicalize_calls=[],
        lookup_result=[],
        canonicalize_result=[{"canonical": "dept-a"}],
    )
    deps = _DummyDeps(dictionaries=provider)
    gateway = ProviderGateway.with_defaults()

    result = gateway.lookup(
        "dictionary.canonicalize",
        deps,
        "Dept A",
        args={"dict_name": "departments", "at": "2026-02-20", "limit": 2},
    )

    assert result == [{"canonical": "dept-a"}]
    assert provider.canonicalize_calls == [
        {"dict_name": "departments", "value": "Dept A", "at": "2026-02-20", "limit": 2}
    ]


def test_dictionary_canonicalize_rejects_unknown_args() -> None:
    provider = _DummyDictionaryProvider(
        lookup_calls=[],
        canonicalize_calls=[],
        lookup_result=[],
        canonicalize_result=[],
    )
    deps = _DummyDeps(dictionaries=provider)
    gateway = ProviderGateway.with_defaults()

    with pytest.raises(ValueError, match="Unknown args"):
        gateway.lookup(
            "dictionary.canonicalize",
            deps,
            "Dept A",
            args={"dict_name": "departments", "fields": ["name"]},
        )
