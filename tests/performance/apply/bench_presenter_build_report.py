"""
Benchmark: ApplyReportPresenter overhead with M outcomes (100/1000).
Measures the cost of converting ApplyResult → ReportCollector.

Usage:
    .venv/bin/python tests/performance/apply/bench_presenter_build_report.py --fast
"""

from __future__ import annotations

import pyperf

from connector.delivery.presenters.apply_report_presenter import ApplyReportPresenter
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.models import DiagnosticItem, DiagnosticSeverity, DiagnosticStage
from connector.domain.planning.plan_models import Plan, PlanMeta, PlanSummary
from connector.domain.planning.record_ref import RecordRef
from connector.domain.reporting.collector import ReportCollector
from connector.usecases.apply.models import ApplyItemOutcome, ApplyResult, ApplySummary


def _make_outcome(i: int) -> ApplyItemOutcome:
    return ApplyItemOutcome(
        record_ref=RecordRef(row_id=f"line:{i}", line_no=i),
        op="create",
        status="FAILED",
        target_id=f"id-{i}",
        diagnostics=(
            DiagnosticItem(
                severity=DiagnosticSeverity.ERROR,
                stage=DiagnosticStage.SINK,
                code="SINK_HTTP_ERROR",
                field=None,
                message=f"HTTP error for item {i}",
            ),
        ),
    )


def _make_result(m: int) -> ApplyResult:
    outcomes = tuple(_make_outcome(i) for i in range(m))
    return ApplyResult(
        summary=ApplySummary(
            created=0,
            updated=0,
            failed=m,
            skipped=0,
            items_total=m,
            rows_with_warnings=0,
            error_stats={"SINK_HTTP_ERROR": m},
        ),
        primary_code=SystemErrorCode.DATA_INVALID,
        all_codes=(SystemErrorCode.DATA_INVALID,),
        fatal_error=False,
        item_outcomes=outcomes,
        outcomes_truncated=False,
    )


def _make_plan() -> Plan:
    return Plan(
        meta=PlanMeta(
            run_id="bench",
            generated_at=None,
            csv_path=None,
            plan_path=None,
            include_deleted=False,
            dataset="employees",
        ),
        summary=PlanSummary(
            rows_total=1000,
            valid_rows=1000,
            failed_rows=0,
            planned_create=1000,
            planned_update=0,
            skipped=0,
        ),
        items=[],
    )


def bench_presenter(loops: int, m: int) -> float:
    result = _make_result(m)
    plan = _make_plan()
    runtime_ctx = {"retries_used": 5}

    total = 0.0
    timer = pyperf.perf_counter
    for _ in range(loops):
        collector = ReportCollector(run_id="bench", command="import-apply")
        t0 = timer()
        ApplyReportPresenter.present(
            result=result,
            collector=collector,
            plan=plan,
            runtime_context=runtime_ctx,
        )
        total += timer() - t0

    return total


def bench_presenter_100(loops: int) -> float:
    return bench_presenter(loops, 100)


def bench_presenter_1000(loops: int) -> float:
    return bench_presenter(loops, 1000)


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.bench_time_func("presenter_100_outcomes", bench_presenter_100)
    runner.bench_time_func("presenter_1000_outcomes", bench_presenter_1000)
