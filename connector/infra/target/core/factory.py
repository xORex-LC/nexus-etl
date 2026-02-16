"""Фабрика TargetRuntime с реестром провайдеров (только core runtime)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from connector.config.app_settings import ApiSettings
from connector.infra.target.core.registry import TargetProviderRegistry
from connector.infra.target.core.runtime import TargetRuntime
from connector.infra.target.providers import AnkeyTargetProvider

TargetRuntimeMode = Literal["core"]
EffectiveTargetRuntimeMode = Literal["core"]


@dataclass(frozen=True)
class TargetRuntimeBuildResult:
    runtime: TargetRuntime
    target_type: str
    requested_mode: TargetRuntimeMode
    effective_mode: EffectiveTargetRuntimeMode


def build_target_runtime(
    api_settings: ApiSettings,
    *,
    transport: object | None = None,
    include_reader: bool = True,
    runtime_mode: str | None = None,
) -> TargetRuntime:
    return build_target_runtime_with_info(
        api_settings,
        transport=transport,
        include_reader=include_reader,
        runtime_mode=runtime_mode,
    ).runtime


def build_target_runtime_with_info(
    api_settings: ApiSettings,
    *,
    transport: object | None = None,
    include_reader: bool = True,
    runtime_mode: str | None = None,
) -> TargetRuntimeBuildResult:
    requested_mode = _resolve_runtime_mode(runtime_mode=runtime_mode)
    provider = _get_default_provider()
    runtime = provider.build_core_runtime(
        api_settings,
        transport=transport,
        include_reader=include_reader,
    )
    return TargetRuntimeBuildResult(
        runtime=runtime,
        target_type=provider.target_type,
        requested_mode=requested_mode,
        effective_mode="core",
    )


def _resolve_runtime_mode(
    *,
    runtime_mode: str | None = None,
) -> TargetRuntimeMode:
    candidate = runtime_mode if runtime_mode is not None else "core"
    normalized = str(candidate).strip().lower()
    allowed: set[str] = {"core"}
    if normalized not in allowed:
        raise ValueError(
            "Invalid target runtime mode: "
            f"{candidate!r}. Expected one of: core",
        )
    return normalized  # type: ignore[return-value]


def _build_default_registry() -> TargetProviderRegistry:
    registry = TargetProviderRegistry()
    registry.register(AnkeyTargetProvider(), default=True)
    return registry


_DEFAULT_PROVIDER_REGISTRY = _build_default_registry()


def _get_default_provider():
    return _DEFAULT_PROVIDER_REGISTRY.get_default()
