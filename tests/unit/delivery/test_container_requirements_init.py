"""
Unit-тесты инициализации ресурсов контейнера по Requirements.

Проверяют:
1. Матрицу инициализации в _init_container_for_requirements().
2. Порядок вызовов для полного профиля (cache -> vault -> api).
"""

from __future__ import annotations

from types import SimpleNamespace

from connector.delivery.cli.containers import _init_container_for_requirements
from connector.delivery.cli.requirements import Requirements


def _container_with_call_log():
    calls: list[str] = []

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
    )
    return container, calls


def test_init_container_for_requirements_cache_only() -> None:
    container, calls = _container_with_call_log()

    _init_container_for_requirements(container, Requirements(requires_cache=True))  # type: ignore[arg-type]

    assert calls == [
        "sqlite.cache_ready",
        "sqlite.identity_ready",
        "cache.gateway",
    ]


def test_init_container_for_requirements_api_only() -> None:
    container, calls = _container_with_call_log()

    _init_container_for_requirements(container, Requirements(requires_api=True))  # type: ignore[arg-type]

    assert calls == ["target.runtime"]


def test_init_container_for_requirements_vault_only() -> None:
    container, calls = _container_with_call_log()

    _init_container_for_requirements(container, Requirements(requires_vault_init=True))  # type: ignore[arg-type]

    assert calls == ["sqlite.vault_ready"]


def test_init_container_for_requirements_full_profile_order() -> None:
    container, calls = _container_with_call_log()

    _init_container_for_requirements(
        container,  # type: ignore[arg-type]
        Requirements(requires_cache=True, requires_vault_init=True, requires_api=True),
    )

    assert calls == [
        "sqlite.cache_ready",
        "sqlite.identity_ready",
        "cache.gateway",
        "sqlite.vault_ready",
        "target.runtime",
    ]
