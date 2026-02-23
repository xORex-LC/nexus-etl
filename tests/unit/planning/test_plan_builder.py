"""
Тесты для PlanBuilder.build_from_stream().
"""

from __future__ import annotations

from connector.domain.models import DiagnosticItem, DiagnosticStage, Identity, RowRef
from connector.domain.planning.plan_builder import PlanBuilder
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.matcher.match_models import ResolvedRow, ResolveOp


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _source_record(line_no: int = 1) -> SourceRecord:
    return SourceRecord(line_no=line_no, record_id=f"r{line_no}", values={})


def _row_ref(line_no: int = 1) -> RowRef:
    return RowRef(line_no=line_no, row_id=f"r{line_no}", identity_primary="k", identity_value="v")


def _resolved_row(op: ResolveOp = ResolveOp.CREATE, line_no: int = 1) -> ResolvedRow:
    return ResolvedRow(
        row_ref=_row_ref(line_no),
        identity=Identity(primary="k", values={"k": "v"}),
        op=op,
        desired_state={"name": f"user{line_no}"},
        changes={},
        target_id=None,
        secret_fields=None,
        secret_lifecycle=None,
    )


def _result_ok(op: ResolveOp = ResolveOp.CREATE, line_no: int = 1) -> TransformResult[ResolvedRow]:
    """TransformResult с валидной resolved-строкой."""
    return TransformResult(
        record=_source_record(line_no),
        row=_resolved_row(op, line_no),
        row_ref=_row_ref(line_no),
        match_key=None,
    )


def _result_none_row(line_no: int = 1) -> TransformResult:
    """TransformResult с row=None — ошибки транспорта."""
    return TransformResult(
        record=_source_record(line_no),
        row=None,
        row_ref=None,
        match_key=None,
    )


def _result_with_errors(line_no: int = 1) -> TransformResult[ResolvedRow]:
    """TransformResult с непустым .errors."""
    error = DiagnosticItem(
        stage=DiagnosticStage.RESOLVE,
        code="test_error",
        field=None,
        message="test",
    )
    return TransformResult(
        record=_source_record(line_no),
        row=_resolved_row(line_no=line_no),
        row_ref=_row_ref(line_no),
        match_key=None,
        errors=(error,),
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_build_from_stream_excludes_none_row():
    result = PlanBuilder().build_from_stream([_result_none_row()])

    assert result.items == []
    assert result.summary.rows_total == 0
    assert result.summary.valid_rows == 0


def test_build_from_stream_excludes_errors():
    result = PlanBuilder().build_from_stream([_result_with_errors()])

    assert result.items == []
    assert result.summary.rows_total == 0


def test_build_from_stream_excludes_conflict_op():
    # CONFLICT пропускается до вызова add_resolved() — счётчики не инкрементируются
    result = PlanBuilder().build_from_stream([_result_ok(op=ResolveOp.CONFLICT)])

    assert result.items == []
    assert result.summary.rows_total == 0
    assert result.summary.valid_rows == 0
    assert result.summary.failed_rows == 0


def test_build_from_stream_includes_create_and_update_ops():
    rows = [
        _result_ok(op=ResolveOp.CREATE, line_no=1),
        _result_ok(op=ResolveOp.UPDATE, line_no=2),
    ]
    result = PlanBuilder().build_from_stream(rows)

    assert result.summary.planned_create == 1
    assert result.summary.planned_update == 1
    assert len(result.items) == 2


def test_build_from_stream_summary_counts_match_input():
    rows = [
        _result_ok(op=ResolveOp.CREATE, line_no=1),
        _result_ok(op=ResolveOp.UPDATE, line_no=2),
        _result_ok(op=ResolveOp.SKIP, line_no=3),
    ]
    result = PlanBuilder().build_from_stream(rows)

    assert result.summary.rows_total == 3
    assert result.summary.valid_rows == 3
    assert result.summary.failed_rows == 0
    assert result.summary.skipped == 1
