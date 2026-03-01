from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from connector.domain.diagnostics.policies import SystemErrorCode
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
from connector.domain.reporting.collector import ReportCollector
from connector.domain.reporting.policy import ReportPolicy
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.result_processor import TransformResultProcessor
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


def test_stage_result_reporter_snapshot_is_immutable() -> None:
    report = ReportCollector(run_id="run-immutable", command="normalize")
    reporter = StageResultReporter(
        report=report,
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
    report = ReportCollector(run_id="run-skip", command="resolve")
    strategy = PlanningStageReportStrategy(
        meta_builder=lambda _r: {"op": "noop"},
        should_skip=lambda _r: True,
    )
    reporter = StageResultReporter(
        report=report,
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
    assert report.build().summary.rows_total == 0


def test_payload_sanitizer_masks_declared_secret_fields() -> None:
    sanitizer = PayloadSanitizer()
    payload = {"plain": "value"}

    sanitized = sanitizer.sanitize(payload, secret_fields=["plain"])

    assert isinstance(sanitized, dict)
    assert sanitized["plain"] == "***"


def test_alias_transform_processor_matches_canonical_reporter_behavior() -> None:
    error = _diag(DiagnosticStage.NORMALIZE, "NORM_ERR", DiagnosticSeverity.ERROR)
    row_result = _make_result(errors=(error,))

    report_alias = ReportCollector(run_id="run-alias", command="normalize")
    alias = TransformResultProcessor(
        report=report_alias,
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        report_stage=DiagnosticStage.NORMALIZE,
        include_upstream_diagnostics=False,
    )
    alias.process(row_result)
    alias_result = alias.finalize()
    alias_envelope = report_alias.build()

    report_new = ReportCollector(run_id="run-canonical", command="normalize")
    reporter = StageResultReporter(
        report=report_new,
        report_policy=ReportPolicy.standard(),
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        strategy=TransformStageReportStrategy(),
        report_stage=DiagnosticStage.NORMALIZE,
        include_upstream_diagnostics=False,
    )
    reporter.process(row_result)
    stats = reporter.publish_context()
    canonical_result = StageCommandResultResolver().resolve(stats)
    canonical_envelope = report_new.build()

    assert alias_envelope.summary == canonical_envelope.summary
    assert alias_envelope.items[0].status == canonical_envelope.items[0].status
    assert alias_envelope.items[0].diagnostics[0].code == canonical_envelope.items[0].diagnostics[0].code
    assert alias_result.system_codes == canonical_result.system_codes == {SystemErrorCode.DATA_INVALID}


def test_stage_result_reporter_uses_explicit_policy_for_include_ok_items() -> None:
    report = ReportCollector(run_id="run-policy-min", command="normalize")
    policy = ReportPolicy.minimal()
    reporter = StageResultReporter(
        report=report,
        report_policy=policy,
        include_items=True,
        context_key="normalize",
        ok_label="normalized_ok",
        failed_label="normalize_failed",
        strategy=TransformStageReportStrategy(),
        report_stage=DiagnosticStage.NORMALIZE,
    )
    reporter.process(_make_result())

    built = report.build()
    assert built.summary.rows_total == 1
    assert len(built.items) == 0


def test_stage_result_reporter_stores_failed_items_even_when_ok_items_disabled() -> None:
    report = ReportCollector(run_id="run-policy-failed", command="normalize")
    policy = ReportPolicy.minimal()
    reporter = StageResultReporter(
        report=report,
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

    built = report.build()
    assert built.summary.rows_blocked == 1
    assert len(built.items) == 1
