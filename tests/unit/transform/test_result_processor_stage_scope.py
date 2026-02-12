from __future__ import annotations

from connector.domain.models import (
    DiagnosticItem,
    DiagnosticSeverity,
    DiagnosticStage,
)
from connector.domain.reporting.collector import ReportCollector
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.result_processor import TransformResultProcessor
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


def test_stage_scoped_report_filters_upstream_diagnostics_but_keeps_failed_status() -> None:
    report = ReportCollector(run_id="run-1", command="normalize")
    processor = TransformResultProcessor(
        report=report,
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        report_stage=DiagnosticStage.NORMALIZE,
        include_upstream_diagnostics=False,
    )
    upstream_error = _diag(DiagnosticStage.MAP, "MAP_ERR", DiagnosticSeverity.ERROR)
    upstream_warning = _diag(DiagnosticStage.MAP, "MAP_WARN", DiagnosticSeverity.WARNING)
    processor.process(_make_result(errors=(upstream_error,), warnings=(upstream_warning,)))
    processor.finalize()

    envelope = report.build()
    assert envelope.summary.rows_blocked == 1
    assert envelope.summary.errors_total == 0
    assert envelope.summary.warnings_total == 0
    assert len(envelope.items) == 1
    assert envelope.items[0].status == "FAILED"
    assert envelope.items[0].diagnostics == []
    assert envelope.items[0].meta["upstream_errors_count"] == 1
    assert envelope.items[0].meta["upstream_warnings_count"] == 1


def test_stage_scoped_report_keeps_only_current_stage_diagnostics() -> None:
    report = ReportCollector(run_id="run-2", command="normalize")
    processor = TransformResultProcessor(
        report=report,
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        report_stage=DiagnosticStage.NORMALIZE,
        include_upstream_diagnostics=False,
    )
    map_error = _diag(DiagnosticStage.MAP, "MAP_ERR", DiagnosticSeverity.ERROR)
    normalize_error = _diag(DiagnosticStage.NORMALIZE, "NORM_ERR", DiagnosticSeverity.ERROR)
    map_warning = _diag(DiagnosticStage.MAP, "MAP_WARN", DiagnosticSeverity.WARNING)
    normalize_warning = _diag(DiagnosticStage.NORMALIZE, "NORM_WARN", DiagnosticSeverity.WARNING)

    processor.process(
        _make_result(
            errors=(map_error, normalize_error),
            warnings=(map_warning, normalize_warning),
        )
    )
    processor.finalize()

    envelope = report.build()
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
    report = ReportCollector(run_id="run-3", command="normalize")
    processor = TransformResultProcessor(
        report=report,
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        report_stage=DiagnosticStage.NORMALIZE,
        include_upstream_diagnostics=True,
    )
    map_error = _diag(DiagnosticStage.MAP, "MAP_ERR", DiagnosticSeverity.ERROR)
    normalize_error = _diag(DiagnosticStage.NORMALIZE, "NORM_ERR", DiagnosticSeverity.ERROR)
    processor.process(_make_result(errors=(map_error, normalize_error)))
    processor.finalize()

    envelope = report.build()
    assert envelope.summary.errors_total == 2
    assert envelope.summary.by_stage["MAP"]["errors_total"] == 1
    assert envelope.summary.by_stage["NORMALIZE"]["errors_total"] == 1
    assert envelope.items[0].meta["upstream_errors_count"] == 0
