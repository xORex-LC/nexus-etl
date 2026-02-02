from __future__ import annotations

from typing import Any

from connector.domain.diagnostics.catalog import ErrorCatalog, build_error, build_warning
from connector.domain.models import DiagnosticItem, DiagnosticSeverity, DiagnosticStage, RowRef


def error(
    stage: DiagnosticStage,
    code: str,
    field: str | None = None,
    message: str | None = None,
    record_ref: RowRef | None = None,
    details: dict[str, Any] | None = None,
    severity: DiagnosticSeverity | None = None,
    *,
    catalog: ErrorCatalog,
) -> DiagnosticItem:
    """
    Назначение:
        Создать DiagnosticItem (error) через текущую фабрику.
    """
    return build_error(
        catalog=catalog,
        stage=stage,
        code=code,
        field=field,
        message=message,
        record_ref=record_ref,
        details=details,
        severity=severity,
    )


def warning(
    stage: DiagnosticStage,
    code: str,
    field: str | None = None,
    message: str | None = None,
    record_ref: RowRef | None = None,
    details: dict[str, Any] | None = None,
    severity: DiagnosticSeverity | None = None,
    *,
    catalog: ErrorCatalog,
) -> DiagnosticItem:
    """
    Назначение:
        Создать DiagnosticItem (warning) через текущую фабрику.
    """
    return build_warning(
        catalog=catalog,
        stage=stage,
        code=code,
        field=field,
        message=message,
        record_ref=record_ref,
        details=details,
        severity=severity,
    )
