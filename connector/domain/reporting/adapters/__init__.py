"""Purpose:
    Canonical adapters для трансляции stage-level результатов в report-layer.

Boundary:
    - Модуль владеет адаптацией `TransformResult -> report item/context stats`.
    - Не владеет orchestration команд и не управляет runtime lifecycle.
    - Legacy wrappers в `transform/core/result_processor.py` должны только
      делегировать в этот пакет (DEC-002 compatibility window).
"""

from connector.domain.reporting.adapters.payload_sanitizer import PayloadSanitizer
from connector.domain.reporting.adapters.result_policy import StageCommandResultResolver
from connector.domain.reporting.adapters.stage_result_reporter import StageResultReporter
from connector.domain.reporting.adapters.stats_accumulator import (
    ExecutionStatsAccumulator,
    StageExecutionStats,
)
from connector.domain.reporting.adapters.strategies import (
    IStageReportStrategy,
    PlanningStageReportStrategy,
    TransformStageReportStrategy,
)

__all__ = [
    "ExecutionStatsAccumulator",
    "IStageReportStrategy",
    "PayloadSanitizer",
    "PlanningStageReportStrategy",
    "StageCommandResultResolver",
    "StageExecutionStats",
    "StageResultReporter",
    "TransformStageReportStrategy",
]
