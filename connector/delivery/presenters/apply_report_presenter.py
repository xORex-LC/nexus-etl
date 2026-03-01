from __future__ import annotations

from typing import Any

from connector.domain.models import RowRef
from connector.domain.planning.plan_models import Plan
from connector.domain.reporting.contracts import ReportContextKey, ReportItemStatus, ReportOpKey
from connector.domain.reporting.diagnostics import to_report_diagnostics
from connector.domain.reporting.events import (
    AddItemEvent,
    AddOpEvent,
    EnsureErrorsTotalAtLeastEvent,
    MergeOpFieldsEvent,
    SetContextEvent,
    SetItemsTruncatedEvent,
    SetRowCountersEvent,
    SetStatusEvent,
)
from connector.domain.reporting.sink import IReportSink
from connector.usecases.apply.models import ApplyResult


class ApplyReportPresenter:
    """Purpose:
        Преобразовать `ApplyResult` в report write calls на delivery-границе.

    Boundary:
        - Пишет только через `IReportSink.emit(...)`.
        - Не читает текущее состояние report context.
    """

    @staticmethod
    def present(
        result: ApplyResult,
        sink: IReportSink,
        plan: Plan,
        apply_context: dict[str, Any] | None = None,
        runtime_context: dict[str, Any] | None = None,
    ) -> None:
        summary = result.summary

        sink.emit(
            SetRowCountersEvent(
                rows_total=summary.items_total,
                rows_passed=summary.created + summary.updated,
                rows_blocked=summary.failed,
                rows_with_warnings=summary.rows_with_warnings,
                rows_skipped=summary.skipped,
            )
        )

        sink.emit(AddOpEvent(name=ReportOpKey.CREATE, ok=summary.created))
        sink.emit(AddOpEvent(name=ReportOpKey.UPDATE, ok=summary.updated))
        sink.emit(AddOpEvent(name=ReportOpKey.SKIP, count=summary.skipped))
        sink.emit(AddOpEvent(name=ReportOpKey.APPLY_FAILED, failed=summary.failed))

        apply_ctx = dict(apply_context or {})
        apply_ctx["error_stats"] = dict(summary.error_stats)
        apply_ctx["retention_stats"] = dict(summary.retention_stats)
        apply_ctx.update(runtime_context or {})
        sink.emit(SetContextEvent(name=ReportContextKey.APPLY, value=apply_ctx))

        planned_create = plan.summary.planned_create if plan.summary else 0
        planned_update = plan.summary.planned_update if plan.summary else 0
        sink.emit(
            MergeOpFieldsEvent(
                name=ReportOpKey.PLAN,
                values={"planned_create": planned_create, "planned_update": planned_update},
            )
        )

        # Compatibility bridge: row-level summary уже pre-aggregated в ApplySummary.
        for outcome in result.item_outcomes:
            row_ref = RowRef(
                line_no=outcome.record_ref.line_no,
                row_id=outcome.record_ref.row_id,
                identity_primary=None,
                identity_value=None,
            )
            errors_diags = [d for d in outcome.diagnostics if _is_error(d)]
            warn_diags = [d for d in outcome.diagnostics if not _is_error(d)]
            report_diagnostics = to_report_diagnostics(errors_diags, warn_diags)
            report_errors = [d for d in report_diagnostics if d.severity == "error"]
            report_warnings = [d for d in report_diagnostics if d.severity == "warning"]
            sink.emit(
                AddItemEvent(
                    status=ReportItemStatus(outcome.status),
                    row_ref=row_ref,
                    payload=None,
                    errors=tuple(report_errors),
                    warnings=tuple(report_warnings),
                    meta={"op": outcome.op, "target_id": outcome.target_id},
                    store=True,
                    preaggregated=True,
                )
            )

        sink.emit(SetItemsTruncatedEvent(value=result.outcomes_truncated))

        # Если outcomes усечены до нуля, по items нельзя надёжно вывести статус.
        # В этом случае используем summary как источник истины.
        if summary.failed > 0:
            sink.emit(EnsureErrorsTotalAtLeastEvent(value=summary.failed))

        passed = summary.created + summary.updated
        if summary.failed == 0:
            sink.emit(SetStatusEvent(status="SUCCESS"))
        elif passed > 0:
            sink.emit(SetStatusEvent(status="PARTIAL"))
        else:
            sink.emit(SetStatusEvent(status="FAILED"))


def _is_error(diag) -> bool:
    severity = getattr(diag, "severity", None)
    if severity is None:
        return True
    if hasattr(severity, "value"):
        return severity.value == "error"
    return str(severity) == "error"
