"""Совместимый вход в модели target-core (legacy import path)."""

from __future__ import annotations

from connector.infra.target.core.models import (
    TargetCheckResult,
    TargetConnectionConfig,
    TargetFaultKind,
    TargetMeta,
    TargetStats,
)

__all__ = [
    "TargetCheckResult",
    "TargetConnectionConfig",
    "TargetFaultKind",
    "TargetMeta",
    "TargetStats",
]
