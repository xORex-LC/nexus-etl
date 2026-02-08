"""
Назначение:
    Обёртки для перевода DSL-issue в диагностические элементы.
"""

from __future__ import annotations

from typing import Iterable

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.context import error as diag_error, warning as diag_warning
from connector.domain.models import DiagnosticItem, DiagnosticStage, RowRef
from connector.domain.transform.dsl.issues import DslIssue, DslSeverity


def append_dsl_issue(
    *,
    errors: list[DiagnosticItem],
    warnings: list[DiagnosticItem],
    stage: DiagnosticStage,
    issue: DslIssue,
    catalog: ErrorCatalog,
    record_ref: RowRef | None,
    on_error: str | None = None,
) -> None:
    """
    Назначение:
        Преобразовать одну DslIssue в DiagnosticItem.
    """
    as_warning = issue.severity == DslSeverity.WARNING
    if on_error == "warn":
        as_warning = True
    if as_warning:
        warnings.append(
            diag_warning(
                stage=stage,
                code=issue.code,
                field=issue.field,
                message=issue.message,
                details=issue.details,
                record_ref=record_ref,
                catalog=catalog,
            )
        )
        return
    errors.append(
        diag_error(
            stage=stage,
            code=issue.code,
            field=issue.field,
            message=issue.message,
            details=issue.details,
            record_ref=record_ref,
            catalog=catalog,
        )
    )


def append_dsl_issues(
    *,
    errors: list[DiagnosticItem],
    warnings: list[DiagnosticItem],
    issues: Iterable[DslIssue],
    stage: DiagnosticStage,
    catalog: ErrorCatalog,
    record_ref: RowRef | None,
    on_error: str | None = None,
) -> None:
    """
    Назначение:
        Преобразовать список DslIssue в DiagnosticItem.
    """
    for issue in issues:
        append_dsl_issue(
            errors=errors,
            warnings=warnings,
            stage=stage,
            issue=issue,
            catalog=catalog,
            record_ref=record_ref,
            on_error=on_error,
        )
