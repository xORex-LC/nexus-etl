"""
Совместимость импортов target spec-моделей на infra-уровне.

Назначение:
    Держать historical import path `connector.infra.target.core.spec_models`
    рабочим, при этом source of truth для моделей перенесён в domain DSL слой.
"""

from __future__ import annotations

from connector.domain.target_dsl.spec_models import (
    FaultRule,
    HealthSpec,
    OperationSpec,
    RedactionSpec,
    RetryConfig,
    RetryDirective,
    RetryRule,
    TargetCapability,
    TargetFaultKind,
    TargetSpec,
)

__all__ = [
    "FaultRule",
    "HealthSpec",
    "OperationSpec",
    "RedactionSpec",
    "RetryConfig",
    "RetryDirective",
    "RetryRule",
    "TargetCapability",
    "TargetFaultKind",
    "TargetSpec",
]

