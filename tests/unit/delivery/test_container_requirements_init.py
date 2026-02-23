"""
Unit-тесты инициализации ресурсов контейнера по Requirements.

Проверяют:
1. Матрицу инициализации в _init_container_for_requirements().
2. Порядок вызовов для полного профиля (cache -> vault -> api -> dictionary).
"""

from __future__ import annotations

from types import SimpleNamespace

from connector.delivery.cli.containers import _init_container_for_requirements
from connector.delivery.cli.requirements import Requirements


def _container_with_call_log(*, dictionary_provider: object | None = None):
    calls: list[str] = []
    provider_sentinel = object() if dictionary_provider is None else dictionary_provider
    pipeline_override = SimpleNamespace(value="__unset__")

    def _init(name: str):
        return SimpleNamespace(init=lambda: calls.append(name))

    def _dictionary_provider():
        calls.append("dictionary.provider")
        return provider_sentinel

    def _pipeline_override(value: object) -> None:
        pipeline_override.value = value
        calls.append("pipeline.dictionaries.override")

    container = SimpleNamespace(
        sqlite=SimpleNamespace(
            cache_ready=_init("sqlite.cache_ready"),
            identity_ready=_init("sqlite.identity_ready"),
            vault_ready=_init("sqlite.vault_ready"),
        ),
        cache=SimpleNamespace(gateway=_init("cache.gateway")),
        target=SimpleNamespace(runtime=_init("target.runtime")),
        dictionary=SimpleNamespace(
            backend=_init("dictionary.backend"),
            provider=_dictionary_provider,
        ),
        pipeline=SimpleNamespace(
            dictionaries=SimpleNamespace(override=_pipeline_override),
        ),
    )
    return container, calls, pipeline_override, provider_sentinel


def test_init_container_for_requirements_cache_only() -> None:
    container, calls, _pipeline_override, _provider = _container_with_call_log()

    _init_container_for_requirements(container, Requirements(requires_cache=True))  # type: ignore[arg-type]

    assert calls == [
        "sqlite.cache_ready",
        "sqlite.identity_ready",
        "cache.gateway",
    ]


def test_init_container_for_requirements_api_only() -> None:
    container, calls, _pipeline_override, _provider = _container_with_call_log()

    _init_container_for_requirements(container, Requirements(requires_api=True))  # type: ignore[arg-type]

    assert calls == ["target.runtime"]


def test_init_container_for_requirements_vault_only() -> None:
    container, calls, _pipeline_override, _provider = _container_with_call_log()

    _init_container_for_requirements(container, Requirements(requires_vault_init=True))  # type: ignore[arg-type]

    assert calls == ["sqlite.vault_ready"]


def test_init_container_for_requirements_full_profile_order() -> None:
    container, calls, _pipeline_override, _provider = _container_with_call_log()

    _init_container_for_requirements(
        container,  # type: ignore[arg-type]
        Requirements(
            requires_cache=True,
            requires_vault_init=True,
            requires_api=True,
            requires_dictionaries=True,
        ),
    )

    assert calls == [
        "sqlite.cache_ready",
        "sqlite.identity_ready",
        "cache.gateway",
        "sqlite.vault_ready",
        "target.runtime",
        "dictionary.backend",
        "dictionary.provider",
        "pipeline.dictionaries.override",
    ]


def test_init_container_for_requirements_dictionaries_only_active_overrides_pipeline() -> None:
    container, calls, pipeline_override, provider = _container_with_call_log()

    _init_container_for_requirements(
        container,  # type: ignore[arg-type]
        Requirements(requires_dictionaries=True),
    )

    assert calls == [
        "dictionary.backend",
        "dictionary.provider",
        "pipeline.dictionaries.override",
    ]
    assert pipeline_override.value is provider


def test_init_container_for_requirements_dictionaries_disabled_keeps_pipeline_default() -> None:
    calls: list[str] = []
    pipeline_override = SimpleNamespace(value="__unset__")

    def _init(name: str):
        return SimpleNamespace(init=lambda: calls.append(name))

    container = SimpleNamespace(
        sqlite=SimpleNamespace(
            cache_ready=_init("sqlite.cache_ready"),
            identity_ready=_init("sqlite.identity_ready"),
            vault_ready=_init("sqlite.vault_ready"),
        ),
        cache=SimpleNamespace(gateway=_init("cache.gateway")),
        target=SimpleNamespace(runtime=_init("target.runtime")),
        dictionary=SimpleNamespace(
            backend=_init("dictionary.backend"),
            provider=lambda: (calls.append("dictionary.provider"), None)[1],
        ),
        pipeline=SimpleNamespace(
            dictionaries=SimpleNamespace(override=lambda _value: calls.append("pipeline.dictionaries.override")),
        ),
    )

    _init_container_for_requirements(
        container,  # type: ignore[arg-type]
        Requirements(requires_dictionaries=True),
    )

    assert calls == [
        "dictionary.backend",
        "dictionary.provider",
    ]
    assert pipeline_override.value == "__unset__"
