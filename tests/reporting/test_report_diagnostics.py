from __future__ import annotations

from connector.domain.models import DiagnosticItem, DiagnosticStage, DiagnosticSeverity
from connector.domain.reporting.diagnostics import split_report_diagnostics, to_report_diagnostics
from connector.domain.reporting.models import ReportDiagnostic


def test_to_report_diagnostics_converts_items_and_keeps_report_diagnostics():
    error_item = DiagnosticItem(
        stage=DiagnosticStage.MAP,
        code="E1",
        field="field_a",
        message="error",
        severity=DiagnosticSeverity.ERROR,
    )
    warning_diag = ReportDiagnostic(
        severity="warning",
        stage=DiagnosticStage.NORMALIZE,
        code="W1",
        field=None,
        message="warn",
        rule="rule-x",
    )

    diagnostics = to_report_diagnostics([error_item], [warning_diag])

    assert len(diagnostics) == 2
    assert diagnostics[0].severity == "error"
    assert diagnostics[0].stage == DiagnosticStage.MAP
    assert diagnostics[0].code == "E1"
    assert diagnostics[0].field == "field_a"
    assert diagnostics[0].message == "error"
    assert diagnostics[1] == warning_diag


def test_split_report_diagnostics_uses_fallback_severity():
    error_item = DiagnosticItem(
        stage=DiagnosticStage.ENRICH,
        code="E2",
        field=None,
        message="error",
        severity=None,
    )
    warning_item = DiagnosticItem(
        stage=DiagnosticStage.VALIDATE,
        code="W2",
        field="field_b",
        message="warn",
        severity=None,
    )

    errors, warnings = split_report_diagnostics([error_item], [warning_item])

    assert len(errors) == 1
    assert errors[0].severity == "error"
    assert errors[0].stage == DiagnosticStage.ENRICH
    assert errors[0].code == "E2"
    assert len(warnings) == 1
    assert warnings[0].severity == "warning"
    assert warnings[0].stage == DiagnosticStage.VALIDATE
    assert warnings[0].code == "W2"
