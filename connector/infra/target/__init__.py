"""
Пакет адаптеров к целевой системе (target).

Предоставляет TargetRuntime — единую точку доступа для delivery-слоя,
скрывая конкретную target-инфраструктуру (HTTP-клиент, retry и т.д.).
"""

from connector.infra.target.core.factory import (
    TargetRuntimeBuildResult,
    build_target_runtime,
    build_target_runtime_with_info,
)
from connector.infra.target.core.models import (
    TargetCheckResult,
    TargetConnectionConfig,
    TargetFaultKind,
    TargetMeta,
    TargetStats,
)
from connector.infra.target.core.runtime import DefaultTargetRuntime, TargetRuntime

__all__ = [
    "build_target_runtime",
    "build_target_runtime_with_info",
    "TargetRuntimeBuildResult",
    "DefaultTargetRuntime",
    "TargetCheckResult",
    "TargetConnectionConfig",
    "TargetFaultKind",
    "TargetMeta",
    "TargetRuntime",
    "TargetStats",
]
