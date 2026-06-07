from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from connector.domain.models import (
    DiagnosticItem,
    DiagnosticSeverity,
    DiagnosticStage,
)
from connector.domain.reporting.adapters.payload_sanitizer import PayloadSanitizer
from connector.domain.reporting.adapters.result_policy import StageCommandResultResolver
from connector.domain.reporting.adapters.stage_result_reporter import StageResultReporter
from connector.domain.reporting.adapters.strategies import (
    PlanningStageReportStrategy,
    TransformStageReportStrategy,
)
from connector.domain.reporting.assembler import ReportAssembler
from connector.domain.reporting.context import InMemoryReportContext
from connector.domain.reporting.policy import ReportPolicy
from connector.domain.reporting.sink import ReportSink
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord


def _diag(stage: DiagnosticStage, code: str, severity: DiagnosticSeverity) -> DiagnosticItem:
    return DiagnosticItem(
        stage=stage,
        code=code,
        field=None,
        message=code,
        severity=severity,
    )


def _make_result(
    *,
    errors: tuple[DiagnosticItem, ...] = (),
    warnings: tuple[DiagnosticItem, ...] = (),
    row: dict[str, object] | None = None,
) -> TransformResult[dict[str, object]]:
    return TransformResult(
        record=SourceRecord(line_no=1, record_id="line:1", values={}),
        row=row if row is not None else {"id": "1"},
        row_ref=None,
        match_key=None,
        meta={},
        secret_candidates={},
        errors=errors,
        warnings=warnings,
    )


def _make_runtime() -> tuple[InMemoryReportContext, ReportSink, ReportAssembler]:
    context = InMemoryReportContext(run_id="run", command="normalize")
    sink = ReportSink(context)
    assembler = ReportAssembler(context=context)
    return context, sink, assembler


def test_stage_result_reporter_snapshot_is_immutable() -> None:
    _context, sink, _assembler = _make_runtime()
    reporter = StageResultReporter(
        sink=sink,
        report_policy=ReportPolicy.standard(),
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        strategy=TransformStageReportStrategy(),
        report_stage=DiagnosticStage.NORMALIZE,
    )
    reporter.process(_make_result())
    snapshot = reporter.snapshot()

    with pytest.raises(FrozenInstanceError):
        snapshot.rows_total = 99


def test_planning_strategy_skip_prevents_row_aggregation() -> None:
    _context, sink, assembler = _make_runtime()
    strategy = PlanningStageReportStrategy(
        meta_builder=lambda _r: {"op": "noop"},
        should_skip=lambda _r: True,
    )
    reporter = StageResultReporter(
        sink=sink,
        report_policy=ReportPolicy.standard(),
        include_items=True,
        context_key="resolve",
        ok_label="resolved_ok",
        failed_label="resolve_failed",
        strategy=strategy,
        report_stage=DiagnosticStage.RESOLVE,
    )

    reporter.process(_make_result())
    snapshot = reporter.snapshot()

    assert snapshot.rows_total == 0
    assert assembler.assemble().summary.rows_total == 0


def test_payload_sanitizer_masks_declared_secret_fields() -> None:
    sanitizer = PayloadSanitizer()
    payload = {"plain": "value"}

    sanitized = sanitizer.sanitize(payload, secret_fields=["plain"])

    assert isinstance(sanitized, dict)
    assert sanitized["plain"] == "***"


def test_stage_result_reporter_uses_explicit_policy_for_include_ok_items() -> None:
    _context, sink, assembler = _make_runtime()
    policy = ReportPolicy.minimal()
    reporter = StageResultReporter(
        sink=sink,
        report_policy=policy,
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        strategy=TransformStageReportStrategy(),
        report_stage=DiagnosticStage.NORMALIZE,
    )
    reporter.process(_make_result())

    built = assembler.assemble()
    assert built.summary.rows_total == 1
    assert len(built.items) == 0


def test_stage_result_reporter_stores_failed_items_even_when_ok_items_disabled() -> None:
    _context, sink, assembler = _make_runtime()
    policy = ReportPolicy.minimal()
    reporter = StageResultReporter(
        sink=sink,
        report_policy=policy,
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        strategy=TransformStageReportStrategy(),
        report_stage=DiagnosticStage.NORMALIZE,
    )
    error = _diag(DiagnosticStage.NORMALIZE, "NORM_ERR", DiagnosticSeverity.ERROR)
    reporter.process(_make_result(errors=(error,)))
    stats = reporter.publish_context()
    result = StageCommandResultResolver().resolve(stats)

    built = assembler.assemble()
    assert built.summary.rows_blocked == 1
    assert len(built.items) == 1
    assert result.ok is False


def test_stage_result_reporter_accepts_multiple_report_stages() -> None:
    _context, sink, assembler = _make_runtime()
    reporter = StageResultReporter(
        sink=sink,
        report_policy=ReportPolicy.standard(),
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        strategy=TransformStageReportStrategy(),
        report_stage=DiagnosticStage.NORMALIZE,
        report_stages=(
            DiagnosticStage.NORMALIZE,
            DiagnosticStage.TOPOLOGY_VALIDATE,
        ),
    )
    topology_error = _diag(
        DiagnosticStage.TOPOLOGY_VALIDATE,
        "TOPOLOGY_SOURCE_UNANCHORED",
        DiagnosticSeverity.ERROR,
    )
    reporter.process(_make_result(errors=(topology_error,)))
    reporter.publish_context()

    built = assembler.assemble()
    assert built.summary.rows_blocked == 1
    assert built.summary.by_stage == {
        "TOPOLOGY_VALIDATE": {"errors_total": 1, "warnings_total": 0}
    }
    assert built.items[0].status == "FAILED"
    assert built.items[0].meta["upstream_errors_count"] == 0
    assert built.items[0].diagnostics[0].stage == "TOPOLOGY_VALIDATE"
