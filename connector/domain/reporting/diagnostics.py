"""
Назначение:
    Преобразование диагностик в report-формат.
"""

from __future__ import annotations

from typing import Iterable

from connector.domain.models import DiagnosticItem
from connector.domain.reporting.models import ReportDiagnostic


def to_report_diagnostics(
    errors: Iterable[DiagnosticItem | ReportDiagnostic] | None,
    warnings: Iterable[DiagnosticItem | ReportDiagnostic] | None,
) -> list[ReportDiagnostic]:
    """
    Назначение:
        Преобразовать DiagnosticItem в ReportDiagnostic.
    """
    diagnostics: list[ReportDiagnostic] = []
    for item in errors or []:
        diagnostics.append(_from_item(item, fallback_severity="error"))
    for item in warnings or []:
        diagnostics.append(_from_item(item, fallback_severity="warning"))
    return diagnostics


def split_report_diagnostics(
    errors: Iterable[DiagnosticItem | ReportDiagnostic] | None,
    warnings: Iterable[DiagnosticItem | ReportDiagnostic] | None,
) -> tuple[list[ReportDiagnostic], list[ReportDiagnostic]]:
    """
    Назначение:
        Вернуть отдельные списки errors/warnings в report-формате.
    """
    diagnostics = to_report_diagnostics(errors, warnings)
    return (
        [item for item in diagnostics if item.severity == "error"],
        [item for item in diagnostics if item.severity == "warning"],
    )


def _from_item(item: DiagnosticItem | ReportDiagnostic, fallback_severity: str) -> ReportDiagnostic:
    if isinstance(item, ReportDiagnostic):
        return item
    severity = item.severity.value if getattr(item, "severity", None) is not None else fallback_severity
    return ReportDiagnostic(
        severity=severity,
        stage=item.stage,
        code=item.code,
        field=item.field,
        message=item.message,
        rule=getattr(item, "rule", None),
        details=getattr(item, "details", None),
    )
