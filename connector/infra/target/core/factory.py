"""
Фабрика TargetRuntime с реестром провайдеров и режимами совместимости.

Режимы:
    - core: собирать только core runtime;
    - legacy: собирать только legacy runtime;
    - auto (по умолчанию): сначала core, при ошибке инициализации переход в legacy.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from connector.config.app_settings import ApiSettings
from connector.infra.target.core.registry import TargetProviderRegistry
from connector.infra.target.core.runtime import TargetRuntime
from connector.infra.target.providers import AnkeyTargetProvider

TargetRuntimeMode = Literal["core", "auto", "legacy"]
EffectiveTargetRuntimeMode = Literal["core", "legacy"]


@dataclass(frozen=True)
class TargetRuntimeBuildResult:
    runtime: TargetRuntime
    target_type: str
    requested_mode: TargetRuntimeMode
    effective_mode: EffectiveTargetRuntimeMode
    fallback_reason: str | None = None


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
    requested_mode = _resolve_runtime_mode(api_settings, runtime_mode=runtime_mode)
    provider = _get_default_provider()

    if requested_mode == "core":
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

    if requested_mode == "legacy":
        runtime = provider.build_legacy_runtime(
            api_settings,
            transport=transport,
            include_reader=include_reader,
        )
        return TargetRuntimeBuildResult(
            runtime=runtime,
            target_type=provider.target_type,
            requested_mode=requested_mode,
            effective_mode="legacy",
        )

    # В режиме `auto` сначала пробуем core, при ошибке переключаемся на legacy.
    try:
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
    except Exception as exc:  # noqa: BLE001
        fallback_reason = f"{type(exc).__name__}: {exc}"
        runtime = provider.build_legacy_runtime(
            api_settings,
            transport=transport,
            include_reader=include_reader,
        )
        return TargetRuntimeBuildResult(
            runtime=runtime,
            target_type=provider.target_type,
            requested_mode=requested_mode,
            effective_mode="legacy",
            fallback_reason=fallback_reason,
        )


def _resolve_runtime_mode(
    api_settings: ApiSettings,
    *,
    runtime_mode: str | None = None,
) -> TargetRuntimeMode:
    candidate = runtime_mode if runtime_mode is not None else api_settings.target_runtime_mode
    normalized = str(candidate).strip().lower()
    allowed: set[str] = {"core", "auto", "legacy"}
    if normalized not in allowed:
        raise ValueError(
            "Invalid target runtime mode: "
            f"{candidate!r}. Expected one of: auto, core, legacy",
        )
    return normalized  # type: ignore[return-value]


def _build_default_registry() -> TargetProviderRegistry:
    registry = TargetProviderRegistry()
    registry.register(AnkeyTargetProvider(), default=True)
    return registry


_DEFAULT_PROVIDER_REGISTRY = _build_default_registry()


def _get_default_provider():
    return _DEFAULT_PROVIDER_REGISTRY.get_default()
