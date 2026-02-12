from __future__ import annotations

from typing import Iterable

from connector.config.config import SettingsIssue, SettingsLoadError
from connector.domain.diagnostics.catalog import ErrorCatalog, build_error, build_warning
from connector.domain.models import DiagnosticItem, DiagnosticSeverity, DiagnosticStage, RowRef


def translate_settings_issue(
    *,
    catalog: ErrorCatalog,
    stage: DiagnosticStage,
    issue: SettingsIssue,
    as_warning: bool,
    record_ref: RowRef | None = None,
) -> DiagnosticItem:
    """
    Назначение:
        Преобразовать SettingsIssue в DiagnosticItem.
    """
    details = {
        "source": issue.source,
        "raw_value": issue.raw_value,
        "hint": issue.hint,
    }
    if as_warning:
        return build_warning(
            catalog=catalog,
            stage=stage,
            code=issue.code,
            field=issue.field_path,
            message=issue.message,
            record_ref=record_ref,
            details=details,
            severity=DiagnosticSeverity.WARNING,
        )
    return build_error(
        catalog=catalog,
        stage=stage,
        code=issue.code,
        field=issue.field_path,
        message=issue.message,
        record_ref=record_ref,
        details=details,
    )


def translate_settings_load_error(
    *,
    catalog: ErrorCatalog,
    stage: DiagnosticStage,
    error: SettingsLoadError,
    record_ref: RowRef | None = None,
) -> list[DiagnosticItem]:
    """
    Назначение:
        Преобразовать SettingsLoadError в список DiagnosticItem.
    """
    return [
        translate_settings_issue(
            catalog=catalog,
            stage=stage,
            issue=issue,
            as_warning=False,
            record_ref=record_ref,
        )
        for issue in error.issues
    ]


def translate_settings_warnings(
    *,
    catalog: ErrorCatalog,
    stage: DiagnosticStage,
    warnings: Iterable[SettingsIssue],
    record_ref: RowRef | None = None,
) -> list[DiagnosticItem]:
    """
    Назначение:
        Преобразовать warning-список SettingsIssue в DiagnosticItem.
    """
    return [
        translate_settings_issue(
            catalog=catalog,
            stage=stage,
            issue=issue,
            as_warning=True,
            record_ref=record_ref,
        )
        for issue in warnings
    ]
