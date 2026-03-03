from __future__ import annotations

from connector.domain.models import (
    DiagnosticItem,
    DiagnosticSeverity,
    DiagnosticStage,
)
from connector.domain.reporting.adapters.stage_result_reporter import StageResultReporter
from connector.domain.reporting.adapters.strategies import TransformStageReportStrategy
from connector.domain.reporting.assembler import ReportAssembler
from connector.domain.reporting.context import InMemoryReportContext
from connector.domain.reporting.policy import ReportPolicy
from connector.domain.reporting.sink import ReportSink
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord


def _make_result(
    *,
    errors: tuple[DiagnosticItem, ...] = (),
    warnings: tuple[DiagnosticItem, ...] = (),
) -> TransformResult[dict[str, object]]:
    return TransformResult(
        record=SourceRecord(line_no=1, record_id="line:1", values={}),
        row={"id": "1"},
        row_ref=None,
        match_key=None,
        meta={},
        secret_candidates={},
        errors=errors,
        warnings=warnings,
    )


def _diag(stage: DiagnosticStage, code: str, severity: DiagnosticSeverity) -> DiagnosticItem:
    return DiagnosticItem(
        stage=stage,
        code=code,
        field=None,
        message=code,
        severity=severity,
    )


def _make_runtime() -> tuple[ReportSink, ReportAssembler]:
    context = InMemoryReportContext(run_id="run", command="normalize")
    return ReportSink(context), ReportAssembler(context=context)


def test_stage_scoped_report_filters_upstream_diagnostics_and_uses_stage_only_status() -> None:
    sink, assembler = _make_runtime()
    reporter = StageResultReporter(
        sink=sink,
        report_policy=ReportPolicy.standard(),
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        strategy=TransformStageReportStrategy(),
        report_stage=DiagnosticStage.NORMALIZE,
        include_upstream_diagnostics=False,
    )
    upstream_error = _diag(DiagnosticStage.MAP, "MAP_ERR", DiagnosticSeverity.ERROR)
    upstream_warning = _diag(DiagnosticStage.MAP, "MAP_WARN", DiagnosticSeverity.WARNING)
    reporter.process(_make_result(errors=(upstream_error,), warnings=(upstream_warning,)))
    reporter.publish_context()

    envelope = assembler.assemble()
    assert envelope.summary.rows_blocked == 0
    assert envelope.summary.rows_passed == 1
    assert envelope.summary.errors_total == 0
    assert envelope.summary.warnings_total == 0
    assert len(envelope.items) == 1
    assert envelope.items[0].status == "OK"
    assert envelope.items[0].diagnostics == []
    assert envelope.items[0].meta["upstream_errors_count"] == 1
    assert envelope.items[0].meta["upstream_warnings_count"] == 1


def test_stage_scoped_report_keeps_only_current_stage_diagnostics() -> None:
    sink, assembler = _make_runtime()
    reporter = StageResultReporter(
        sink=sink,
        report_policy=ReportPolicy.standard(),
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        strategy=TransformStageReportStrategy(),
        report_stage=DiagnosticStage.NORMALIZE,
        include_upstream_diagnostics=False,
    )
    map_error = _diag(DiagnosticStage.MAP, "MAP_ERR", DiagnosticSeverity.ERROR)
    normalize_error = _diag(DiagnosticStage.NORMALIZE, "NORM_ERR", DiagnosticSeverity.ERROR)
    map_warning = _diag(DiagnosticStage.MAP, "MAP_WARN", DiagnosticSeverity.WARNING)
    normalize_warning = _diag(DiagnosticStage.NORMALIZE, "NORM_WARN", DiagnosticSeverity.WARNING)

    reporter.process(
        _make_result(
            errors=(map_error, normalize_error),
            warnings=(map_warning, normalize_warning),
        )
    )
    reporter.publish_context()

    envelope = assembler.assemble()
    assert envelope.summary.errors_total == 1
    assert envelope.summary.warnings_total == 1
    assert envelope.summary.by_stage == {
        "NORMALIZE": {"errors_total": 1, "warnings_total": 1}
    }
    diagnostics = envelope.items[0].diagnostics
    assert {item.code for item in diagnostics} == {"NORM_ERR", "NORM_WARN"}
    assert envelope.items[0].meta["upstream_errors_count"] == 1
    assert envelope.items[0].meta["upstream_warnings_count"] == 1


def test_include_upstream_diagnostics_keeps_full_chain() -> None:
    sink, assembler = _make_runtime()
    reporter = StageResultReporter(
        sink=sink,
        report_policy=ReportPolicy.debug(),
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        strategy=TransformStageReportStrategy(),
        report_stage=DiagnosticStage.NORMALIZE,
        include_upstream_diagnostics=True,
    )
    map_error = _diag(DiagnosticStage.MAP, "MAP_ERR", DiagnosticSeverity.ERROR)
    normalize_error = _diag(DiagnosticStage.NORMALIZE, "NORM_ERR", DiagnosticSeverity.ERROR)
    reporter.process(_make_result(errors=(map_error, normalize_error)))
    reporter.publish_context()

    envelope = assembler.assemble()
    assert envelope.summary.errors_total == 2
    assert envelope.summary.by_stage["MAP"]["errors_total"] == 1
    assert envelope.summary.by_stage["NORMALIZE"]["errors_total"] == 1
    assert envelope.items[0].meta["upstream_errors_count"] == 0
