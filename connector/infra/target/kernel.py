"""Совместимый вход в TargetKernel target-core (legacy import path)."""

from __future__ import annotations

from connector.infra.target.core.kernel import (
    ResolvedHttpOperation,
    ResolvedRetryAction,
    TargetKernel,
)

__all__ = ["ResolvedHttpOperation", "ResolvedRetryAction", "TargetKernel"]
