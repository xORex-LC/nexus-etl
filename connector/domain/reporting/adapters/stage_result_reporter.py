"""Purpose:
    Canonical adapter `TransformResult -> ReportEvent` для stage-reporting.

Boundary:
    - Владеет row-level адаптацией и stage counters.
    - Не формирует CommandResult (это ответственность StageCommandResultResolver).
    - Не выполняет orchestration pipeline/runtime.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from connector.domain.models import DiagnosticItem, DiagnosticStage, RowRef
from connector.domain.reporting.adapters.payload_sanitizer import PayloadSanitizer
from connector.domain.reporting.adapters.stats_accumulator import (
    ExecutionStatsAccumulator,
    StageExecutionStats,
)
from connector.domain.reporting.contracts import ReportContextKey, ReportItemStatus
from connector.domain.reporting.adapters.strategies import IStageReportStrategy
from connector.domain.reporting.events import AddItemEvent, SetContextEvent
from connector.domain.reporting.policy import ReportPolicy
from connector.domain.reporting.diagnostics import split_report_diagnostics
from connector.domain.reporting.sink import IReportSink

if TYPE_CHECKING:
    from connector.domain.transform.core.result import TransformResult


class StageResultReporter:
    """Purpose:
        Единый обработчик результатов стадии для report-layer.

    Contract:
        - Применяет stage policy фильтрации diagnostics.
        - Записывает row-items только через IReportSink.
        - Публикует stage context через `publish_context()`.
    """

    def __init__(
        self,
        *,
        sink: IReportSink,
        report_policy: ReportPolicy,
        include_items: bool,
        context_key: ReportContextKey | str,
        ok_label: str,
        failed_label: str,
        strategy: IStageReportStrategy,
        report_stage: DiagnosticStage | None = None,
        include_upstream_diagnostics: bool = False,
        stats_accumulator: ExecutionStatsAccumulator | None = None,
        payload_sanitizer: PayloadSanitizer | None = None,
    ) -> None:
        self._sink = sink
        self.report_policy = report_policy
        self.include_items = self.report_policy.resolve_include_ok_items(include_items)
        self.context_key = context_key
        self.ok_label = ok_label
        self.failed_label = failed_label
        self.strategy = strategy
        self.report_stage = report_stage
        self.include_upstream_diagnostics = self.report_policy.resolve_include_upstream_diagnostics(
            include_upstream_diagnostics
        )
        self._stats = stats_accumulator or ExecutionStatsAccumulator()
        self._payload_sanitizer = payload_sanitizer or PayloadSanitizer()

    def process(
        self,
        result: TransformResult | None,
        *,
        row_ref: RowRef | None = None,
        force_failed: bool = False,
        errors_override: list[DiagnosticItem] | None = None,
        warnings_override: list[DiagnosticItem] | None = None,
    ) -> None:
        """Purpose:
            Обработать один stage result и записать report item при необходимости.

        Algorithm:
            1) Применить skip-policy strategy.
            2) Отфильтровать diagnostics до stage scope.
            3) Посчитать статус по stage-local ошибкам (stage-only policy).
            4) Обновить counters и записать item через IReportSink.
        """
        if self.strategy.should_skip(result):
            return

        eff_errors_all = (
            list(errors_override)
            if errors_override is not None
            else list(result.errors if result else [])
        )
        eff_warnings_all = (
            list(warnings_override)
            if warnings_override is not None
            else list(result.warnings if result else [])
        )
        (
            eff_errors,
            eff_warnings,
            upstream_errors_count,
            upstream_warnings_count,
        ) = self._filter_for_report(
            errors=eff_errors_all,
            warnings=eff_warnings_all,
        )

        # Stage-only policy: статус определяется только diagnostics текущей stage.
        has_errors = force_failed or bool(eff_errors)
        status = ReportItemStatus.FAILED if has_errors else ReportItemStatus.OK
        self._stats.on_row(has_errors=has_errors, has_warnings=bool(eff_warnings))

        secret_fields: list[str] = []
        if result:
            meta_secret_fields = result.meta.get("secret_fields") if result.meta else None
            if isinstance(meta_secret_fields, (list, tuple, set)):
                secret_fields = [str(item) for item in meta_secret_fields if item]
            elif result.secret_candidates:
                secret_fields = [str(key) for key in result.secret_candidates.keys() if key]
            self._stats.on_secret_fields(secret_fields)

        should_store = (
            (status == ReportItemStatus.FAILED and self.report_policy.capabilities.include_failed_items)
            or self.include_items
        )
        effective_row_ref = row_ref or (result.row_ref if result else None)
        if effective_row_ref is None and result is not None:
            effective_row_ref = RowRef(
                line_no=result.record.line_no,
                row_id=result.record.record_id,
                identity_primary=None,
                identity_value=None,
            )

        row_payload = None
        if should_store and result is not None:
            payload_obj = self.strategy.build_payload(result)
            row_payload = self._payload_sanitizer.sanitize(
                payload_obj,
                secret_fields=secret_fields,
            )

        meta = self.strategy.build_meta(
            result,
            upstream_errors_count=upstream_errors_count,
            upstream_warnings_count=upstream_warnings_count,
            secret_fields=secret_fields,
        )

        report_errors, report_warnings = split_report_diagnostics(eff_errors, eff_warnings)
        self._sink.emit(
            AddItemEvent(
                status=status,
                row_ref=effective_row_ref,
                payload=row_payload,
                errors=tuple(report_errors),
                warnings=tuple(report_warnings),
                meta=meta,
                store=should_store,
                preaggregated=False,
            )
        )

    def snapshot(self) -> StageExecutionStats:
        """Purpose:
            Вернуть immutable stage counters snapshot.
        """
        return self._stats.snapshot()

    def publish_context(self) -> StageExecutionStats:
        """Purpose:
            Записать stage counters в report.context и вернуть snapshot.
        """
        snapshot = self.snapshot()
        self._sink.emit(
            SetContextEvent(
                name=self.context_key,
                value=snapshot.to_context_payload(
                    ok_label=self.ok_label,
                    failed_label=self.failed_label,
                ),
            )
        )
        return snapshot

    def _filter_for_report(
        self,
        *,
        errors: list[DiagnosticItem],
        warnings: list[DiagnosticItem],
    ) -> tuple[list[DiagnosticItem], list[DiagnosticItem], int, int]:
        if self.include_upstream_diagnostics or self.report_stage is None:
            return errors, warnings, 0, 0
        report_errors = [item for item in errors if _diag_stage_equals(item, self.report_stage)]
        report_warnings = [item for item in warnings if _diag_stage_equals(item, self.report_stage)]
        upstream_errors_count = len(errors) - len(report_errors)
        upstream_warnings_count = len(warnings) - len(report_warnings)
        return report_errors, report_warnings, upstream_errors_count, upstream_warnings_count


def _diag_stage_equals(item: DiagnosticItem, stage: DiagnosticStage) -> bool:
    item_stage: Any = item.stage
    if item_stage == stage:
        return True
    if isinstance(item_stage, str):
        return item_stage.upper() == stage.value
    return False
