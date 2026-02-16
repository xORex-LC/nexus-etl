"""Совместимый вход в spec-модели target-core (legacy import path)."""

from __future__ import annotations

from connector.infra.target.core.spec_models import (
    FaultRule,
    HealthCheckSpec,
    HttpOperationData,
    OperationSpec,
    PagingSpec,
    RedactionSpec,
    RetryConfig,
    RetryDirective,
    RetryRule,
    TargetCapability,
    TargetSpec,
)

__all__ = [
    "FaultRule",
    "HealthCheckSpec",
    "HttpOperationData",
    "OperationSpec",
    "PagingSpec",
    "RedactionSpec",
    "RetryConfig",
    "RetryDirective",
    "RetryRule",
    "TargetCapability",
    "TargetSpec",
]
