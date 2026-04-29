"""
Назначение:
    Маппинг runtime/handler результата в report-события.

Граница ответственности:
    - Обрабатывает только canonical `DomainCommandResult`.
    - Не управляет DI lifecycle и не вызывает handler.
    - Не содержит compatibility-веток устаревших runtime-результатов.
"""

from __future__ import annotations

from typing import Any

from connector.domain.diagnostics.catalog import build_error
from connector.domain.diagnostics.command_result import CommandResult as DomainCommandResult
from connector.domain.models import DiagnosticSeverity, DiagnosticStage
from connector.domain.reporting.context import IReportContext
from connector.domain.reporting.contracts import ReportItemStatus
from connector.domain.reporting.diagnostics import split_report_diagnostics
from connector.domain.reporting.events import AddItemEvent
from connector.domain.reporting.models import ReportDiagnostic
from connector.domain.reporting.sink import IReportSink


def apply_runtime_result_to_report(
    sink: IReportSink,
    context: IReportContext,
    result: DomainCommandResult | None,
    *,
    command_name: str,
    source: str,
    secondary: bool,
) -> None:
    """
    Назначение:
        Нормализовать runtime/handler результат в report item.

    Контракт:
        - Входной результат — только `DomainCommandResult | None`.
        - Для secondary-ошибок демотирует severity в warning.
    """
    if result is None:
        return
    if not isinstance(result, DomainCommandResult):
        raise TypeError(
            "Runtime result must be DomainCommandResult | None; "
            f"got {type(result).__name__}"
        )
    _apply_domain_result(
        sink=sink,
        context=context,
        result=result,
        command_name=command_name,
        source=source,
        secondary=secondary,
    )


def build_runtime_error_result(
    *,
    catalog,
    command_name: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> DomainCommandResult:
    """
    Назначение:
        Сконструировать `DomainCommandResult` для runtime-исключений.
    """
    diagnostic = build_error(
        catalog=catalog,
        stage=stage_for_command(command_name),
        code="INTERNAL_ERROR",
        field=None,
        message=message,
        record_ref=None,
        details=details,
    )
    result = DomainCommandResult()
    result.add_diagnostics([diagnostic], catalog)
    return result


def stage_for_command(command_name: str) -> DiagnosticStage:
    """
    Назначение:
        Сопоставить runtime command name -> diagnostic stage.
    """
    normalized = command_name.replace("-", "_").lower()
    stage_map = {
        "mapping": DiagnosticStage.MAP,
        "normalize": DiagnosticStage.NORMALIZE,
        "enrich": DiagnosticStage.ENRICH,
        "match": DiagnosticStage.MATCH,
        "resolve": DiagnosticStage.RESOLVE,
        "import_plan": DiagnosticStage.PLAN,
        "import_apply": DiagnosticStage.APPLY,
        "cache_refresh": DiagnosticStage.CACHE,
        "cache_clear": DiagnosticStage.CACHE,
        "cache_status": DiagnosticStage.CACHE,
        "vault_management_init": DiagnosticStage.SINK,
        "vault_management_status": DiagnosticStage.SINK,
        "vault_management_rotate": DiagnosticStage.SINK,
        "vault_management_rewrap": DiagnosticStage.SINK,
    }
    return stage_map.get(normalized, DiagnosticStage.SINK)


def _apply_domain_result(
    *,
    sink: IReportSink,
    context: IReportContext,
    result: DomainCommandResult,
    command_name: str,
    source: str,
    secondary: bool,
) -> None:
    """
    Назначение:
        Перенести `DomainCommandResult` в report item с synthetic fallback.
    """
    stage = stage_for_command(command_name)
    errors: list[ReportDiagnostic] = []
    warnings: list[ReportDiagnostic] = []

    if result.diagnostics:
        domain_errors, domain_warnings = _split_domain_diagnostics(result.diagnostics)
        report_errors, report_warnings = split_report_diagnostics(domain_errors, domain_warnings)
        errors.extend(report_errors)
        warnings.extend(report_warnings)
    elif not result.ok and _needs_synthetic_diagnostic(context=context, secondary=secondary):
        primary_code = result.primary_code()
        errors.append(
            ReportDiagnostic(
                severity="error",
                stage=stage,
                code=primary_code.value,
                field=None,
                message=f"Command failed with system code: {primary_code.value}",
                details={
                    "system_code": primary_code.value,
                    "system_codes": sorted(code.value for code in result.system_codes),
                },
            )
        )

    if not errors and not warnings:
        return

    errors, warnings = _with_secondary_policy(errors=errors, warnings=warnings, secondary=secondary)
    sink.emit(
        AddItemEvent(
            status=ReportItemStatus.FAILED if errors else ReportItemStatus.OK,
            row_ref=None,
            payload=None,
            errors=tuple(errors),
            warnings=tuple(warnings),
            meta={
                "source": source,
                "secondary": secondary,
                "synthetic": bool(not result.diagnostics),
                "system_codes": sorted(code.value for code in result.system_codes),
            },
            store=True,
            preaggregated=False,
        )
    )


def _split_domain_diagnostics(diagnostics: list[Any]) -> tuple[list[Any], list[Any]]:
    """
    Назначение:
        Разделить diagnostics по severity для `split_report_diagnostics()`.
    """
    errors: list[Any] = []
    warnings: list[Any] = []
    for diagnostic in diagnostics:
        if _is_warning(diagnostic):
            warnings.append(diagnostic)
        else:
            errors.append(diagnostic)
    return errors, warnings


def _is_warning(diagnostic: Any) -> bool:
    """
    Назначение:
        Определить warning-severity для DiagnosticItem/ReportDiagnostic.
    """
    severity = getattr(diagnostic, "severity", None)
    if severity is None:
        return False
    if isinstance(severity, DiagnosticSeverity):
        return severity == DiagnosticSeverity.WARNING
    if hasattr(severity, "value"):
        return str(severity.value).lower() == "warning"
    return str(severity).lower() == "warning"


def _with_secondary_policy(
    *,
    errors: list[ReportDiagnostic],
    warnings: list[ReportDiagnostic],
    secondary: bool,
) -> tuple[list[ReportDiagnostic], list[ReportDiagnostic]]:
    """
    Назначение:
        Secondary-policy: demote error -> warning.
    """
    if not secondary:
        return errors, warnings
    downgraded = [*warnings]
    for diag in errors:
        downgraded.append(
            ReportDiagnostic(
                severity="warning",
                stage=diag.stage,
                code=diag.code,
                field=diag.field,
                message=diag.message,
                rule=diag.rule,
                details=diag.details,
            )
        )
    return [], downgraded


def _needs_synthetic_diagnostic(*, context: IReportContext, secondary: bool) -> bool:
    """
    Назначение:
        Нужен ли synthetic runtime diagnostic для non-OK без diagnostics.
    """
    if secondary:
        return True
    summary = context.summary_snapshot()
    return summary.rows_blocked == 0 and summary.errors_total == 0


__all__ = [
    "apply_runtime_result_to_report",
    "build_runtime_error_result",
    "stage_for_command",
]
