"""Фабрика сборки ``TargetRuntime`` через зарегистрированные providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from connector.config.models import ApiConfig as ApiSettings
from connector.infra.target.core.runtime import TargetRuntime
from connector.infra.target.providers.registry import (
    build_default_target_provider_registry,
)

TargetRuntimeMode = Literal["core"]
EffectiveTargetRuntimeMode = Literal["core"]


@dataclass(frozen=True)
class TargetRuntimeBuildResult:
    """Результат сборки runtime с метаданными режима и провайдера."""

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
    target_type: str | None = None,
) -> TargetRuntime:
    """Собрать ``TargetRuntime`` для target-провайдера.

    Упрощённый фасад над ``build_target_runtime_with_info``, возвращающий только runtime.
    """
    return build_target_runtime_with_info(
        api_settings,
        transport=transport,
        include_reader=include_reader,
        runtime_mode=runtime_mode,
        target_type=target_type,
    ).runtime


def build_target_runtime_with_info(
    api_settings: ApiSettings,
    *,
    transport: object | None = None,
    include_reader: bool = True,
    runtime_mode: str | None = None,
    target_type: str | None = None,
) -> TargetRuntimeBuildResult:
    """Собрать runtime и вернуть служебную информацию о выборе провайдера.

    Алгоритм:
        1. Нормализовать runtime-mode и проверить допустимые значения.
        2. Построить реестр доступных providers.
        3. Выбрать provider по ``target_type`` либо provider по умолчанию.
        4. Собрать runtime выбранным provider.
    """
    requested_mode = _resolve_runtime_mode(runtime_mode=runtime_mode)
    registry = build_default_target_provider_registry(api_settings)
    provider = registry.get(target_type) if target_type else registry.get_default()
    runtime = provider.build_core_runtime(
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
    """Нормализовать runtime-mode и проверить поддерживаемые значения."""
    candidate = runtime_mode if runtime_mode is not None else "core"
    normalized = str(candidate).strip().lower()
    allowed: set[str] = {"core"}
    if normalized not in allowed:
        raise ValueError(
            "Invalid target runtime mode: "
            f"{candidate!r}. Expected one of: core",
        )
    return normalized  # type: ignore[return-value]
