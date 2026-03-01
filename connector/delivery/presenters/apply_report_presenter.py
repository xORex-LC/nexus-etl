from __future__ import annotations

from typing import Any

from connector.domain.models import RowRef
from connector.domain.planning.plan_models import Plan
from connector.domain.reporting.contracts import ReportContextKey, ReportItemStatus, ReportOpKey
from connector.domain.reporting.diagnostics import to_report_diagnostics
from connector.domain.reporting.ports import ReportWritePort
from connector.usecases.apply.models import ApplyResult


class ApplyReportPresenter:
    """Purpose:
        Преобразовать `ApplyResult` в report write calls на delivery-границе.

    Boundary:
        - Не мутирует внутренние структуры collector напрямую.
        - Пишет только через `ReportWritePort` API (DEC-003).
    """

    @staticmethod
    def present(
        result: ApplyResult,
        collector: ReportWritePort,
        plan: Plan,
        runtime_context: dict[str, Any] | None = None,
    ) -> None:
        summary = result.summary

        collector.set_row_counters(
            rows_total=summary.items_total,
            rows_passed=summary.created + summary.updated,
            rows_blocked=summary.failed,
            rows_with_warnings=summary.rows_with_warnings,
            rows_skipped=summary.skipped,
        )

        collector.add_op(ReportOpKey.CREATE, ok=summary.created)
        collector.add_op(ReportOpKey.UPDATE, ok=summary.updated)
        collector.add_op(ReportOpKey.SKIP, count=summary.skipped)
        collector.add_op(ReportOpKey.APPLY_FAILED, failed=summary.failed)

        # Дополняем существующий context["apply"], чтобы не потерять поля из handler.
        apply_ctx = dict(collector.get_context(ReportContextKey.APPLY, {}))
        apply_ctx["error_stats"] = dict(summary.error_stats)
        apply_ctx["retention_stats"] = dict(summary.retention_stats)
        apply_ctx.update(runtime_context or {})
        collector.set_context(ReportContextKey.APPLY, apply_ctx)

        planned_create = plan.summary.planned_create if plan.summary else 0
        planned_update = plan.summary.planned_update if plan.summary else 0
        collector.merge_op_fields(
            ReportOpKey.PLAN,
            {"planned_create": planned_create, "planned_update": planned_update},
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
            collector.add_item_preaggregated(
                status=ReportItemStatus(outcome.status),
                row_ref=row_ref,
                payload=None,
                errors=report_errors,
                warnings=report_warnings,
                meta={"op": outcome.op, "target_id": outcome.target_id},
                store=True,
            )

        collector.set_items_truncated(result.outcomes_truncated)

        # Если outcomes усечены до нуля, по items нельзя надёжно вывести статус.
        # В этом случае используем summary как источник истины.
        if summary.failed > 0:
            collector.ensure_errors_total_at_least(summary.failed)

        passed = summary.created + summary.updated
        if summary.failed == 0:
            collector.set_status("SUCCESS")
        elif passed > 0:
            collector.set_status("PARTIAL")
        else:
            collector.set_status("FAILED")


def _is_error(diag) -> bool:
    severity = getattr(diag, "severity", None)
    if severity is None:
        return True
    if hasattr(severity, "value"):
        return severity.value == "error"
    return str(severity) == "error"
