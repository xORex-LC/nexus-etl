"""
Unit-тесты для ApplyReportPresenter.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.delivery.presenters.apply_report_presenter import ApplyReportPresenter
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.models import DiagnosticItem, DiagnosticSeverity, DiagnosticStage
from connector.domain.planning.plan_models import Plan, PlanMeta, PlanSummary
from connector.domain.planning.record_ref import RecordRef
from connector.domain.reporting.assembler import ReportAssembler
from connector.domain.reporting.context import InMemoryReportContext
from connector.domain.reporting.sink import IReportSink, ReportSink
from connector.usecases.apply.models import ApplyItemOutcome, ApplyResult, ApplySummary


def _make_summary(
    created: int = 0,
    updated: int = 0,
    failed: int = 0,
    skipped: int = 0,
    items_total: int = 0,
    rows_with_warnings: int = 0,
    error_stats: dict | None = None,
) -> ApplySummary:
    return ApplySummary(
        created=created,
        updated=updated,
        failed=failed,
        skipped=skipped,
        items_total=items_total or (created + updated + failed),
        rows_with_warnings=rows_with_warnings,
        error_stats=error_stats or {},
    )


def _make_result(
    summary: ApplySummary | None = None,
    outcomes: tuple[ApplyItemOutcome, ...] = (),
    primary_code: SystemErrorCode = SystemErrorCode.OK,
    all_codes: tuple[SystemErrorCode, ...] | None = None,
    fatal_error: bool = False,
    outcomes_truncated: bool = False,
) -> ApplyResult:
    s = summary or _make_summary()
    return ApplyResult(
        summary=s,
        primary_code=primary_code,
        all_codes=all_codes or (primary_code,),
        fatal_error=fatal_error,
        item_outcomes=outcomes,
        outcomes_truncated=outcomes_truncated,
    )


def _make_plan(planned_create: int = 0, planned_update: int = 0) -> Plan:
    return Plan(
        meta=PlanMeta(
            run_id="r",
            generated_at=None,
            csv_path=None,
            plan_path=None,
            include_deleted=False,
            dataset="employees",
        ),
        summary=PlanSummary(
            rows_total=planned_create + planned_update,
            valid_rows=planned_create + planned_update,
            failed_rows=0,
            planned_create=planned_create,
            planned_update=planned_update,
            skipped=0,
        ),
        items=[],
    )


def _make_error_diag(code: str = "SINK_HTTP_ERROR") -> DiagnosticItem:
    return DiagnosticItem(
        severity=DiagnosticSeverity.ERROR,
        stage=DiagnosticStage.SINK,
        code=code,
        field=None,
        message="test error",
    )


def _make_warn_diag(code: str = "FIELD_WARNING") -> DiagnosticItem:
    return DiagnosticItem(
        severity=DiagnosticSeverity.WARNING,
        stage=DiagnosticStage.APPLY,
        code=code,
        field="some_field",
        message="test warning",
    )


def _make_runtime() -> tuple[InMemoryReportContext, ReportSink, ReportAssembler]:
    context = InMemoryReportContext(run_id="r", command="import-apply")
    sink = ReportSink(context)
    return context, sink, ReportAssembler(context=context)


@dataclass
class _SpySink(IReportSink):
    calls: list[str]

    def emit(self, event) -> None:
        self.calls.append(type(event).__name__)


class TestPresenterSummary:
    def test_sets_summary_counters(self):
        summary = _make_summary(created=3, updated=2, failed=1, skipped=5, items_total=6, rows_with_warnings=1)
        result = _make_result(summary=summary)
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=_make_plan())
        built = assembler.assemble()

        assert built.summary.rows_total == 6
        assert built.summary.rows_passed == 5
        assert built.summary.rows_blocked == 1
        assert built.summary.rows_skipped == 5
        assert built.summary.rows_with_warnings == 1

    def test_sets_ops(self):
        summary = _make_summary(created=3, updated=2, failed=1, skipped=5)
        result = _make_result(summary=summary)
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=_make_plan())
        built = assembler.assemble()

        assert built.summary.ops["create"]["ok"] == 3
        assert built.summary.ops["update"]["ok"] == 2
        assert built.summary.ops["skip"]["count"] == 5
        assert built.summary.ops["apply_failed"]["failed"] == 1

    def test_sets_plan_ops(self):
        result = _make_result()
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(
            result=result,
            sink=sink,
            plan=_make_plan(planned_create=10, planned_update=5),
        )

        built = assembler.assemble()
        assert built.summary.ops["plan"]["planned_create"] == 10
        assert built.summary.ops["plan"]["planned_update"] == 5

    def test_no_double_counting_with_outcomes(self):
        outcome = ApplyItemOutcome(
            record_ref=RecordRef(row_id="line:1", line_no=1),
            op="create",
            status="FAILED",
            target_id="id-1",
            diagnostics=(_make_error_diag(),),
        )
        summary = _make_summary(created=0, failed=1, items_total=1)
        result = _make_result(summary=summary, outcomes=(outcome,))
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=_make_plan())
        built = assembler.assemble()

        assert built.summary.rows_total == 1
        assert built.summary.rows_blocked == 1


class TestPresenterContext:
    def test_sets_error_stats_in_context(self):
        summary = _make_summary(failed=2, error_stats={"SINK_HTTP_ERROR": 1, "INTERNAL_ERROR": 1})
        result = _make_result(summary=summary)
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=_make_plan())

        ctx = assembler.assemble().context["apply"]
        assert ctx["error_stats"]["SINK_HTTP_ERROR"] == 1
        assert ctx["error_stats"]["INTERNAL_ERROR"] == 1

    def test_sets_runtime_context(self):
        result = _make_result()
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(
            result=result,
            sink=sink,
            plan=_make_plan(),
            runtime_context={"retries_used": 3},
        )

        assert assembler.assemble().context["apply"]["retries_used"] == 3

    def test_merges_with_existing_context(self):
        result = _make_result(summary=_make_summary(error_stats={"E": 1}))
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(
            result=result,
            sink=sink,
            plan=_make_plan(),
            apply_context={"plan_path": "/tmp/plan.json", "dry_run": False},
            runtime_context={"retries_used": 2},
        )

        ctx = assembler.assemble().context["apply"]
        assert ctx["plan_path"] == "/tmp/plan.json"
        assert ctx["dry_run"] is False
        assert ctx["error_stats"] == {"E": 1}
        assert ctx["retries_used"] == 2


class TestPresenterItems:
    def test_adds_failed_item_with_diagnostics(self):
        ref = RecordRef(row_id="line:1", line_no=10)
        outcome = ApplyItemOutcome(
            record_ref=ref,
            op="create",
            status="FAILED",
            target_id="id-1",
            diagnostics=(_make_error_diag(),),
        )
        result = _make_result(
            summary=_make_summary(failed=1, error_stats={"SINK_HTTP_ERROR": 1}),
            outcomes=(outcome,),
            primary_code=SystemErrorCode.DATA_INVALID,
        )
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=_make_plan())

        built = assembler.assemble()
        assert len(built.items) == 1
        item = built.items[0]
        assert item.status == "FAILED"
        assert item.row_ref is not None
        assert item.row_ref.row_id == "line:1"
        assert item.row_ref.line_no == 10
        assert item.meta["op"] == "create"
        assert item.meta["target_id"] == "id-1"

    def test_preserves_record_ref_none_line_no_as_none(self):
        ref = RecordRef(row_id="line:1", line_no=None)
        outcome = ApplyItemOutcome(
            record_ref=ref,
            op="create",
            status="FAILED",
            target_id="id-1",
            diagnostics=(_make_error_diag(),),
        )
        result = _make_result(summary=_make_summary(failed=1), outcomes=(outcome,))
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=_make_plan())

        assert assembler.assemble().items[0].row_ref.line_no is None

    def test_no_items_when_all_ok(self):
        result = _make_result(summary=_make_summary(created=5))
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=_make_plan())

        assert len(assembler.assemble().items) == 0

    def test_sets_items_truncated_from_outcomes_truncated(self):
        outcomes = tuple(
            ApplyItemOutcome(
                record_ref=RecordRef(row_id=f"line:{i}", line_no=i),
                op="create",
                status="FAILED",
                target_id=f"id-{i}",
                diagnostics=(_make_error_diag(),),
            )
            for i in range(3)
        )
        result = _make_result(
            summary=_make_summary(failed=10, error_stats={"E": 10}),
            outcomes=outcomes,
            outcomes_truncated=True,
        )
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=_make_plan())

        assert assembler.assemble().meta.items_truncated is True

    def test_items_not_truncated_when_flag_false(self):
        outcome = ApplyItemOutcome(
            record_ref=RecordRef(row_id="line:1", line_no=1),
            op="create",
            status="FAILED",
            target_id="id-1",
            diagnostics=(_make_error_diag(),),
        )
        result = _make_result(summary=_make_summary(failed=1), outcomes=(outcome,), outcomes_truncated=False)
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=_make_plan())

        assert assembler.assemble().meta.items_truncated is False

    def test_counts_diagnostics_in_summary(self):
        outcome = ApplyItemOutcome(
            record_ref=RecordRef(row_id="line:1", line_no=1),
            op="create",
            status="FAILED",
            target_id="id-1",
            diagnostics=(_make_error_diag(), _make_warn_diag()),
        )
        result = _make_result(summary=_make_summary(failed=1), outcomes=(outcome,))
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=_make_plan())

        built = assembler.assemble()
        assert built.summary.errors_total == 1
        assert built.summary.warnings_total == 1

    def test_status_failed_when_outcomes_truncated_to_zero(self):
        result = _make_result(
            summary=_make_summary(created=0, updated=0, failed=3, items_total=3, error_stats={"E": 3}),
            outcomes=(),
            outcomes_truncated=True,
        )
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=_make_plan())

        built = assembler.assemble()
        assert built.status == "FAILED"
        assert built.summary.errors_total >= 1

    def test_status_partial_when_has_passed_and_failed(self):
        result = _make_result(
            summary=_make_summary(created=2, updated=0, failed=1, items_total=3, error_stats={"E": 1}),
            outcomes=(),
            outcomes_truncated=True,
        )
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=_make_plan())

        built = assembler.assemble()
        assert built.status == "PARTIAL"


class TestPresenterNoPlanSummary:
    def test_handles_none_plan_summary(self):
        result = _make_result()
        plan = Plan(
            meta=PlanMeta(
                run_id="r",
                generated_at=None,
                csv_path=None,
                plan_path=None,
                include_deleted=False,
                dataset="employees",
            ),
            summary=None,
            items=[],
        )
        _context, sink, assembler = _make_runtime()

        ApplyReportPresenter.present(result=result, sink=sink, plan=plan)

        built = assembler.assemble()
        assert built.summary.ops["plan"]["planned_create"] == 0
        assert built.summary.ops["plan"]["planned_update"] == 0


class TestPresenterSinkContract:
    def test_uses_sink_events_only(self):
        calls: list[str] = []
        spy_sink = _SpySink(calls=calls)
        outcome = ApplyItemOutcome(
            record_ref=RecordRef(row_id="line:1", line_no=1),
            op="create",
            status="FAILED",
            target_id="id-1",
            diagnostics=(_make_error_diag(),),
        )
        result = _make_result(
            summary=_make_summary(created=0, updated=0, failed=1, items_total=1, error_stats={"E": 1}),
            outcomes=(outcome,),
            outcomes_truncated=True,
        )

        ApplyReportPresenter.present(result=result, sink=spy_sink, plan=_make_plan())

        assert "SetRowCountersEvent" in calls
        assert "AddItemEvent" in calls
        assert "SetItemsTruncatedEvent" in calls
        assert "SetStatusEvent" in calls
