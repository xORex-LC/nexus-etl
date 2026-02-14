from __future__ import annotations

from typing import Any

from connector.domain.models import DiagnosticStage, RowRef
from connector.domain.planning.plan_models import Plan
from connector.domain.reporting.collector import ReportCollector
from connector.domain.reporting.diagnostics import to_report_diagnostics
from connector.domain.reporting.models import ReportItem
from connector.usecases.apply.models import ApplyResult


class ApplyReportPresenter:
    """Преобразует ApplyResult → ReportCollector (delivery-side adapter)."""

    @staticmethod
    def present(
        result: ApplyResult,
        collector: ReportCollector,
        plan: Plan,
        runtime_context: dict[str, Any] | None = None,
    ) -> None:
        summary = result.summary

        collector.summary.rows_total = summary.items_total
        collector.summary.rows_passed = summary.created + summary.updated
        collector.summary.rows_blocked = summary.failed
        collector.summary.rows_with_warnings = summary.rows_with_warnings

        collector.add_op("create", ok=summary.created)
        collector.add_op("update", ok=summary.updated)
        collector.add_op("skip", count=summary.skipped)
        collector.add_op("apply_failed", failed=summary.failed)

        # Merge into existing context["apply"] (handler may have set plan_path/opts)
        apply_ctx = dict(collector.context.get("apply", {}))
        apply_ctx["error_stats"] = dict(summary.error_stats)
        apply_ctx.update(runtime_context or {})
        collector.set_context("apply", apply_ctx)

        planned_create = plan.summary.planned_create if plan.summary else 0
        planned_update = plan.summary.planned_update if plan.summary else 0
        collector.summary.ops.setdefault("plan", {})["planned_create"] = planned_create
        collector.summary.ops.setdefault("plan", {})["planned_update"] = planned_update

        # Build items directly (bypass add_item to avoid double-counting summary)
        for outcome in result.item_outcomes:
            row_ref = RowRef(
                line_no=outcome.record_ref.line_no or 0,
                row_id=outcome.record_ref.row_id,
                identity_primary=None,
                identity_value=None,
            )
            errors_diags = [d for d in outcome.diagnostics if _is_error(d)]
            warn_diags = [d for d in outcome.diagnostics if not _is_error(d)]
            report_diagnostics = to_report_diagnostics(errors_diags, warn_diags)
            report_errors = [d for d in report_diagnostics if d.severity == "error"]
            report_warnings = [d for d in report_diagnostics if d.severity == "warning"]
            diagnostics = [*report_errors, *report_warnings]
            collector.items.append(
                ReportItem(
                    status=outcome.status,
                    row_ref=row_ref,
                    payload=None,
                    diagnostics=diagnostics,
                    meta={"op": outcome.op, "target_id": outcome.target_id},
                )
            )
            # Count diagnostics into summary
            for d in report_errors:
                collector.summary.errors_total += 1
                stage_key = d.stage.value if isinstance(d.stage, DiagnosticStage) else str(d.stage)
                entry = collector.summary.by_stage.setdefault(stage_key, {"errors_total": 0, "warnings_total": 0})
                entry["errors_total"] += 1
            for d in report_warnings:
                collector.summary.warnings_total += 1
                stage_key = d.stage.value if isinstance(d.stage, DiagnosticStage) else str(d.stage)
                entry = collector.summary.by_stage.setdefault(stage_key, {"errors_total": 0, "warnings_total": 0})
                entry["warnings_total"] += 1

        if result.outcomes_truncated:
            collector.meta.items_truncated = True

        # When outcomes are truncated to zero, diagnostics counters from items are not enough
        # to derive status reliably. Use summary counters as source of truth.
        if summary.failed > 0 and collector.summary.errors_total == 0:
            collector.summary.errors_total = summary.failed

        passed = summary.created + summary.updated
        if summary.failed == 0:
            collector.status = "SUCCESS"
        elif passed > 0:
            collector.status = "PARTIAL"
        else:
            collector.status = "FAILED"


def _is_error(diag) -> bool:
    severity = getattr(diag, "severity", None)
    if severity is None:
        return True
    if hasattr(severity, "value"):
        return severity.value == "error"
    return str(severity) == "error"
