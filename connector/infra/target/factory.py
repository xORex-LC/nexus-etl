"""Совместимый вход в фабрику TargetRuntime target-core (legacy import path)."""

from __future__ import annotations

from connector.infra.target.core.factory import (
    EffectiveTargetRuntimeMode,
    TargetRuntimeBuildResult,
    TargetRuntimeMode,
    build_target_runtime,
    build_target_runtime_with_info,
)

__all__ = [
    "EffectiveTargetRuntimeMode",
    "TargetRuntimeBuildResult",
    "TargetRuntimeMode",
    "build_target_runtime",
    "build_target_runtime_with_info",
]
