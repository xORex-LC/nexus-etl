"""Purpose:
    Legacy compatibility wrappers для старого result-processor API.

Boundary:
    - Реальной canonical реализацией является `StageResultReporter` из
      `connector.domain.reporting.adapters.*` (DEC-002).
    - Классы ниже сохраняются на окно совместимости 1 релиз и должны
      делегировать всю бизнес-логику в reporting adapters.
"""

from __future__ import annotations

from typing import Any, Callable

from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.models import DiagnosticItem, DiagnosticStage, RowRef
from connector.domain.reporting.adapters.result_policy import StageCommandResultResolver
from connector.domain.reporting.adapters.stage_result_reporter import StageResultReporter
from connector.domain.reporting.adapters.strategies import (
    PlanningStageReportStrategy,
    TransformStageReportStrategy,
)
from connector.domain.transform.core.result import TransformResult


class TransformResultProcessor:
    """Purpose:
        Legacy alias над StageResultReporter.

    Compatibility:
        - Сохраняет старую сигнатуру конструктора/методов.
        - Не содержит самостоятельной бизнес-логики row processing.
        - `finalize()` сохранён как bridge и делегирует policy в resolver.
    """

    def __init__(
        self,
        *,
        report,
        include_items: bool,
        context_key: str,
        ok_label: str,
        failed_label: str,
        payload_builder: Callable[[TransformResult], Any] | None = None,
        report_stage: DiagnosticStage | None = None,
        include_upstream_diagnostics: bool = False,
    ) -> None:
        self._reporter = StageResultReporter(
            report=report,
            include_items=include_items,
            context_key=context_key,
            ok_label=ok_label,
            failed_label=failed_label,
            strategy=TransformStageReportStrategy(payload_builder=payload_builder),
            report_stage=report_stage,
            include_upstream_diagnostics=include_upstream_diagnostics,
        )
        self._result_resolver = StageCommandResultResolver()

    def process(
        self,
        result: TransformResult | None,
        *,
        row_ref: RowRef | None = None,
        force_failed: bool = False,
        errors_override: list[DiagnosticItem] | None = None,
        warnings_override: list[DiagnosticItem] | None = None,
    ) -> None:
        self._reporter.process(
            result,
            row_ref=row_ref,
            force_failed=force_failed,
            errors_override=errors_override,
            warnings_override=warnings_override,
        )

    def snapshot(self):
        """Purpose:
            Legacy pass-through к immutable snapshot canonical reporter-а.
        """
        return self._reporter.snapshot()

    def finalize(self) -> CommandResult:
        """Purpose:
            Legacy bridge: записать context и вернуть CommandResult.

        Compatibility:
            Новый код должен использовать `publish_context() + resolver.resolve(...)`
            напрямую, без зависимости от finalize() у wrapper-класса.
        """
        stats = self._reporter.publish_context()
        return self._result_resolver.resolve(stats)

    @property
    def rows_total(self) -> int:
        return self._reporter.snapshot().rows_total

    @property
    def ok_rows(self) -> int:
        return self._reporter.snapshot().ok_rows

    @property
    def failed_rows(self) -> int:
        return self._reporter.snapshot().failed_rows

    @property
    def warnings_rows(self) -> int:
        return self._reporter.snapshot().warnings_rows

    @property
    def vault_candidates_rows(self) -> int:
        return self._reporter.snapshot().vault_candidates_rows

    @property
    def vault_candidates_fields_total(self) -> int:
        return self._reporter.snapshot().vault_candidates_fields_total


class PlanningResultProcessor(TransformResultProcessor):
    """Purpose:
        Legacy alias для planning-потоков (match/resolve).

    Compatibility:
        - Сигнатура сохранена для внешних импортов.
        - Логика делегируется в PlanningStageReportStrategy + StageResultReporter.
    """

    def __init__(
        self,
        *,
        report,
        include_items: bool,
        context_key: str,
        ok_label: str,
        failed_label: str,
        meta_builder: Callable[[TransformResult], dict[str, Any] | None],
        should_skip: Callable[[TransformResult], bool] | None = None,
        payload_builder: Callable[[TransformResult], Any] | None = None,
        report_stage: DiagnosticStage | None = None,
        include_upstream_diagnostics: bool = False,
    ) -> None:
        self._reporter = StageResultReporter(
            report=report,
            include_items=include_items,
            context_key=context_key,
            ok_label=ok_label,
            failed_label=failed_label,
            strategy=PlanningStageReportStrategy(
                meta_builder=meta_builder,
                should_skip=should_skip,
                payload_builder=payload_builder,
            ),
            report_stage=report_stage,
            include_upstream_diagnostics=include_upstream_diagnostics,
        )
        self._result_resolver = StageCommandResultResolver()
