from __future__ import annotations

import pytest

from connector.infra.target.core.registry import (
    MissingTargetProviderError,
    TargetProviderRegistry,
)


class _ProviderA:
    target_type = "a"

    def build_core_runtime(self, *_args, **_kwargs):  # pragma: no cover - not used
        raise NotImplementedError

    def build_legacy_runtime(self, *_args, **_kwargs):  # pragma: no cover - not used
        raise NotImplementedError


class _ProviderB:
    target_type = "b"

    def build_core_runtime(self, *_args, **_kwargs):  # pragma: no cover - not used
        raise NotImplementedError

    def build_legacy_runtime(self, *_args, **_kwargs):  # pragma: no cover - not used
        raise NotImplementedError


def test_registry_registers_and_resolves_default_provider() -> None:
    registry = TargetProviderRegistry()
    a = _ProviderA()
    b = _ProviderB()

    registry.register(a, default=True)
    registry.register(b)

    assert registry.get_default() is a
    assert registry.get("b") is b


def test_registry_rejects_duplicate_target_type() -> None:
    registry = TargetProviderRegistry()
    registry.register(_ProviderA(), default=True)
    with pytest.raises(ValueError):
        registry.register(_ProviderA())


def test_registry_raises_for_missing_provider() -> None:
    registry = TargetProviderRegistry()
    with pytest.raises(MissingTargetProviderError):
        registry.get("missing")


def test_registry_raises_when_default_is_not_defined() -> None:
    registry = TargetProviderRegistry()
    with pytest.raises(MissingTargetProviderError):
        registry.get_default()
