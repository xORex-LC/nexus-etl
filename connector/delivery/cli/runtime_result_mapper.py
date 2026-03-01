"""Purpose:
    Маппинг runtime/handler результатов в report items.

Boundary:
    - Преобразует `DomainCommandResult` и legacy runtime results в report-level diagnostics.
    - Не управляет DI lifecycle и не вызывает handler.
    - Legacy mapping (`CliCommandResult`/`int`) поддерживается только в compatibility window.
"""

from __future__ import annotations

from typing import Any

from connector.domain.diagnostics.catalog import build_error
from connector.domain.diagnostics.command_result import CommandResult as DomainCommandResult
from connector.domain.models import DiagnosticSeverity, DiagnosticStage
from connector.domain.reporting.collector import ReportCollector
from connector.domain.reporting.contracts import ReportContextKey, ReportItemStatus, normalize_item_status
from connector.domain.reporting.diagnostics import split_report_diagnostics
from connector.domain.reporting.models import ReportDiagnostic

from connector.delivery.cli.result import CommandResult as CliCommandResult
from connector.delivery.cli.result_adapter import adapt_runtime_result


def apply_runtime_result_to_report(
    report: ReportCollector,
    result: Any,
    *,
    command_name: str,
    source: str,
    secondary: bool,
) -> None:
    """Purpose:
        Нормализовать runtime/handler результат в report items.

    Contract:
        - Canonical path: `DomainCommandResult`.
        - Legacy compatibility path: `CliCommandResult`/`int` через result adapter.
        - Для secondary-ошибок демотирует severity в warning.
    """
    adapted = adapt_runtime_result(result)
    if adapted.kind == "none":
        return
    if adapted.kind == "domain":
        _apply_domain_result(
            report=report,
            result=adapted.value,
            command_name=command_name,
            source=source,
            secondary=secondary,
        )
        return
    if adapted.kind == "legacy_cli":
        _apply_legacy_cli_result(
            report=report,
            result=adapted.value,
            source=source,
            secondary=secondary,
        )
        return
    if adapted.kind == "legacy_int":
        _apply_legacy_exit_code(
            report=report,
            command_name=command_name,
            exit_code=adapted.value,
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
    """Purpose:
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
    """Purpose:
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
    }
    return stage_map.get(normalized, DiagnosticStage.SINK)


def _apply_legacy_exit_code(
    *,
    report: ReportCollector,
    command_name: str,
    exit_code: int,
    source: str,
    secondary: bool,
) -> None:
    """Purpose:
        Compatibility mapping для legacy int-result в report item.
    """
    if exit_code == 0:
        return
    severity = "warning" if secondary else "error"
    diagnostic = ReportDiagnostic(
        severity=severity,
        stage=stage_for_command(command_name),
        code=f"EXIT_{exit_code}",
        field=None,
        message=f"Command returned non-zero exit code: {exit_code}",
        details={"exit_code": exit_code},
    )
    errors, warnings = _with_secondary_policy(
        errors=[diagnostic] if severity == "error" else [],
        warnings=[diagnostic] if severity == "warning" else [],
        secondary=secondary,
    )
    report.add_item(
        status=ReportItemStatus.FAILED if errors else ReportItemStatus.OK,
        row_ref=None,
        payload=None,
        errors=errors,
        warnings=warnings,
        meta={"source": source, "secondary": secondary, "synthetic": True},
    )


def _apply_legacy_cli_result(
    *,
    report: ReportCollector,
    result: CliCommandResult,
    source: str,
    secondary: bool,
) -> None:
    """Purpose:
        Compatibility mapping для legacy delivery `CliCommandResult`.
    """
    for item in result.items:
        report_errors, report_warnings = split_report_diagnostics(item.get("errors"), item.get("warnings"))
        report_errors, report_warnings = _with_secondary_policy(
            errors=report_errors,
            warnings=report_warnings,
            secondary=secondary,
        )
        item_status = ReportItemStatus.FAILED if report_errors else (
            ReportItemStatus.OK if secondary else normalize_item_status(item.get("status", "OK"))
        )
        report.add_item(
            status=item_status,
            row_ref=item.get("row_ref"),
            payload=item.get("payload"),
            errors=report_errors,
            warnings=report_warnings,
            meta={
                **(item.get("meta") or {}),
                "source": source,
                "secondary": secondary,
            },
            store=item.get("store", True),
        )

    if result.errors or result.warnings:
        report_errors, report_warnings = split_report_diagnostics(result.errors, result.warnings)
        report_errors, report_warnings = _with_secondary_policy(
            errors=report_errors,
            warnings=report_warnings,
            secondary=secondary,
        )
        report.add_item(
            status=ReportItemStatus.FAILED if report_errors else ReportItemStatus.OK,
            row_ref=None,
            payload=None,
            errors=report_errors,
            warnings=report_warnings,
            meta={"source": source, "secondary": secondary},
        )

    if result.stats:
        report.set_context(ReportContextKey.STATS, result.stats)


def _apply_domain_result(
    *,
    report: ReportCollector,
    result: DomainCommandResult,
    command_name: str,
    source: str,
    secondary: bool,
) -> None:
    """Purpose:
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
    elif not result.ok and _needs_synthetic_diagnostic(report=report, secondary=secondary):
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
    report.add_item(
        status=ReportItemStatus.FAILED if errors else ReportItemStatus.OK,
        row_ref=None,
        payload=None,
        errors=errors,
        warnings=warnings,
        meta={
            "source": source,
            "secondary": secondary,
            "synthetic": bool(not result.diagnostics),
            "system_codes": sorted(code.value for code in result.system_codes),
        },
    )


def _split_domain_diagnostics(diagnostics: list[Any]) -> tuple[list[Any], list[Any]]:
    """Purpose:
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
    """Purpose:
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
    """Purpose:
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


def _needs_synthetic_diagnostic(*, report: ReportCollector, secondary: bool) -> bool:
    """Purpose:
        Нужен ли synthetic runtime diagnostic для non-OK без diagnostics.
    """
    if secondary:
        return True
    # Если row-level ошибки уже есть в отчете, synthetic runtime-item не добавляем.
    return report.summary.rows_blocked == 0 and report.summary.errors_total == 0


__all__ = [
    "apply_runtime_result_to_report",
    "build_runtime_error_result",
    "stage_for_command",
]
