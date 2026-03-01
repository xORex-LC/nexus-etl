"""
Назначение:
    Оркестрация CLI runtime lifecycle (init -> handler -> report finalize -> shutdown)
    и единый маппинг результатов выполнения в report items.

Граница ответственности:
    - Владеет только delivery-оркестрацией и адаптацией runtime/result ошибок в report.
    - Не содержит бизнес-правил use-case стадий и не управляет их внутренней диагностикой.
"""

from __future__ import annotations

import inspect
import logging
import sqlite3
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import typer

from connector.common.time import getDurationMs
from connector.config.config import SettingsLoadError
from connector.config.models import AppConfig
from connector.config.diagnostics import translate_settings_load_error
from connector.domain.diagnostics.catalog import build_error
from connector.domain.diagnostics.command_result import CommandResult as DomainCommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.dsl.diagnostics import translate_dsl_load_error
from connector.domain.dsl.issues import DslLoadError
from connector.domain.reporting.diagnostics import split_report_diagnostics
from connector.domain.reporting.collector import ReportCollector
from connector.domain.reporting.models import ReportDiagnostic
from connector.domain.secrets.errors import VaultDomainError
from connector.infra.artifacts.report_writer import createEmptyReport, finalizeReport, writeReportJson
from connector.infra.logging.setup import StdStreamToLogger, TeeStream, createCommandLogger, logEvent
from connector.datasets.registry import get_spec, resolve_dataset_name
from connector.domain.transform_dsl import load_source_spec_for_dataset, resolve_source_location
from connector.delivery.cli.containers import AppContainer, _init_container_for_requirements
from connector.delivery.cli.context import BoundCommandContext, CommandContext, UnboundCommandContext
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli.result import CommandResult as CliCommandResult
from connector.domain.models import DiagnosticSeverity, DiagnosticStage


ReportHandler = Callable[..., Any]


class RuntimeErrorWithCode(RuntimeError):
    """
    Назначение:
        Ошибка runtime-валидации с явным кодом выхода.
    """

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def run_with_report(
    *,
    ctx: UnboundCommandContext,
    command_name: str,
    opts: Any,
    handler: ReportHandler,
    requirements: Requirements,
) -> None:
    """
    Назначение:
        Унифицированная обвязка выполнения команд с записью отчёта.

    Поведение:
        - создаёт логгер и report
        - валидирует требования
        - вызывает handler
        - финализирует отчёт
        - завершает процесс через typer.Exit
    """

    app_config = _require_app_settings(ctx)
    paths = app_config.paths
    observability = app_config.observability
    run_id = ctx.run_id

    start_monotonic = time.monotonic()
    logger, log_file_path = createCommandLogger(
        commandName=command_name,
        logDir=paths.log_dir,
        runId=run_id,
        logLevel=observability.log_level,
    )
    ctx = replace(ctx, logger=logger)

    report = createEmptyReport(runId=run_id, command=command_name, configSources=_config_sources(ctx))

    csv_path = _get_opt(opts, ("csv_path", "csv", "input_csv"))
    if csv_path:
        report.set_context("input", {"csv_path": Path(csv_path).name})

    report_items_limit = _get_opt(opts, ("report_items_limit", "items_limit"))
    if report_items_limit is None:
        report_items_limit = observability.report_items_limit
    report.set_meta(items_limit=report_items_limit)

    dataset = _resolve_dataset_opt(opts, app_config)
    if dataset is not None:
        report.set_meta(dataset=dataset)

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    stdout_logger_stream = StdStreamToLogger(logger, logging.INFO, run_id, "stdout")
    stderr_logger_stream = StdStreamToLogger(logger, logging.ERROR, run_id, "stderr")

    sys.stdout = TeeStream(original_stdout, stdout_logger_stream)
    sys.stderr = TeeStream(original_stderr, stderr_logger_stream)

    exit_result: int | DomainCommandResult | CliCommandResult | None = None
    container: AppContainer | None = None

    try:
        logEvent(logger, logging.INFO, run_id, "core", "Command started")

        _validate_requirements(ctx, opts, requirements)

        container = AppContainer()
        container.app_config.override(app_config)
        api_transport = _get_opt(opts, ("api_transport",))
        if api_transport is not None:
            container.target.transport.override(api_transport)
        init_result = _initialize_container_resources(
            container=container,
            requirements=requirements,
            logger=logger,
            run_id=run_id,
        )
        if init_result is not None:
            exit_result = init_result
            _apply_cli_result_to_report(
                report,
                exit_result,
                command_name=command_name,
                source="runtime_init",
                secondary=False,
            )
        else:
            bound_ctx = _bind_context_with_container(ctx, container=container)
            exit_result = _call_handler(handler, bound_ctx, opts, report)
            _apply_cli_result_to_report(
                report,
                exit_result,
                command_name=command_name,
                source="handler_result",
                secondary=False,
            )

    except SettingsLoadError as exc:
        stage = _stage_for_command(command_name)
        diags = translate_settings_load_error(
            catalog=ctx.catalog,
            stage=stage,
            error=exc,
            record_ref=None,
        )
        logEvent(logger, logging.ERROR, run_id, "config", f"Settings error: {exc}")
        _echo_command_diagnostics("ERROR: invalid settings configuration", diags)
        result = DomainCommandResult()
        result.add_diagnostics(diags, ctx.catalog)
        exit_result = result
        _apply_cli_result_to_report(
            report,
            exit_result,
            command_name=command_name,
            source="settings_load_error",
            secondary=False,
        )
    except DslLoadError as exc:
        stage = _stage_for_command(command_name)
        diag = translate_dsl_load_error(
            catalog=ctx.catalog,
            stage=stage,
            error=exc,
            record_ref=None,
        )
        logEvent(logger, logging.ERROR, run_id, "dsl", f"{exc.code}: {exc}")
        typer.echo(f"ERROR: {exc.code}: {exc}", err=True)
        result = DomainCommandResult()
        result.add_diagnostics([diag], ctx.catalog)
        exit_result = result
        _apply_cli_result_to_report(
            report,
            exit_result,
            command_name=command_name,
            source="dsl_load_error",
            secondary=False,
        )
    except RuntimeErrorWithCode as exc:
        logEvent(logger, logging.ERROR, run_id, "config", str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        exit_result = _runtime_error_result(
            catalog=ctx.catalog,
            command_name=command_name,
            message=str(exc),
            details={"runtime_exit_code": exc.exit_code, "runtime_error": "RuntimeErrorWithCode"},
        )
        _apply_cli_result_to_report(
            report,
            exit_result,
            command_name=command_name,
            source="runtime_validation_error",
            secondary=False,
        )
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "core", f"Command failed: {exc}")
        typer.echo("ERROR: command failed (see logs/report)", err=True)
        exit_result = _runtime_error_result(
            catalog=ctx.catalog,
            command_name=command_name,
            message=str(exc),
            details={"runtime_error": exc.__class__.__name__},
        )
        _apply_cli_result_to_report(
            report,
            exit_result,
            command_name=command_name,
            source="runtime_exception",
            secondary=False,
        )
    finally:
        try:
            shutdown_result = _shutdown_container_resources(
                container=container,
                logger=logger,
                run_id=run_id,
                emit_user_error=exit_result is None,
            )
            if shutdown_result is not None:
                _apply_cli_result_to_report(
                    report,
                    shutdown_result,
                    command_name=command_name,
                    source="runtime_shutdown",
                    secondary=exit_result is not None,
                )
            if exit_result is None and shutdown_result is not None:
                exit_result = shutdown_result

            finalize_result = _finalize_report_artifacts(
                report=report,
                start_monotonic=start_monotonic,
                paths=paths,
                log_file_path=log_file_path,
                command_name=command_name,
                run_id=run_id,
                logger=logger,
                emit_user_error=exit_result is None,
            )
            if finalize_result is not None:
                _apply_cli_result_to_report(
                    report,
                    finalize_result,
                    command_name=command_name,
                    source="runtime_finalize",
                    secondary=exit_result is not None,
                )
            if exit_result is None and finalize_result is not None:
                exit_result = finalize_result
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr

        if exit_result is not None:
            raise typer.Exit(code=_exit_code_from_result(exit_result))


def run_without_report(
    *,
    ctx: UnboundCommandContext,
    command_name: str,
    opts: Any,
    handler: ReportHandler,
    requirements: Requirements,
) -> None:
    """
    Назначение:
        Унифицированная обвязка выполнения команд без формирования отчёта.
    """

    app_config = _require_app_settings(ctx)
    paths = app_config.paths
    observability = app_config.observability
    run_id = ctx.run_id

    start_monotonic = time.monotonic()
    logger, log_file_path = createCommandLogger(
        commandName=command_name,
        logDir=paths.log_dir,
        runId=run_id,
        logLevel=observability.log_level,
    )
    ctx = replace(ctx, logger=logger)

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    stdout_logger_stream = StdStreamToLogger(logger, logging.INFO, run_id, "stdout")
    stderr_logger_stream = StdStreamToLogger(logger, logging.ERROR, run_id, "stderr")

    sys.stdout = TeeStream(original_stdout, stdout_logger_stream)
    sys.stderr = TeeStream(original_stderr, stderr_logger_stream)

    exit_result: int | DomainCommandResult | CliCommandResult | None = None
    container: AppContainer | None = None

    try:
        logEvent(logger, logging.INFO, run_id, "core", "Command started")

        _validate_requirements(ctx, opts, requirements)

        container = AppContainer()
        container.app_config.override(app_config)
        api_transport = _get_opt(opts, ("api_transport",))
        if api_transport is not None:
            container.target.transport.override(api_transport)
        init_result = _initialize_container_resources(
            container=container,
            requirements=requirements,
            logger=logger,
            run_id=run_id,
        )
        if init_result is not None:
            exit_result = init_result
        else:
            bound_ctx = _bind_context_with_container(ctx, container=container)
            exit_result = _call_handler(handler, bound_ctx, opts, None)

    except SettingsLoadError as exc:
        stage = _stage_for_command(command_name)
        diags = translate_settings_load_error(
            catalog=ctx.catalog,
            stage=stage,
            error=exc,
            record_ref=None,
        )
        logEvent(logger, logging.ERROR, run_id, "config", f"Settings error: {exc}")
        _echo_command_diagnostics("ERROR: invalid settings configuration", diags)
        result = DomainCommandResult()
        result.add_diagnostics(diags, ctx.catalog)
        exit_result = result
    except DslLoadError as exc:
        stage = _stage_for_command(command_name)
        diag = translate_dsl_load_error(
            catalog=ctx.catalog,
            stage=stage,
            error=exc,
            record_ref=None,
        )
        logEvent(logger, logging.ERROR, run_id, "dsl", f"{exc.code}: {exc}")
        typer.echo(f"ERROR: {exc.code}: {exc}", err=True)
        result = DomainCommandResult()
        result.add_diagnostics([diag], ctx.catalog)
        exit_result = result
    except RuntimeErrorWithCode as exc:
        logEvent(logger, logging.ERROR, run_id, "config", str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        exit_result = _runtime_error_result(
            catalog=ctx.catalog,
            command_name=command_name,
            message=str(exc),
            details={"runtime_exit_code": exc.exit_code, "runtime_error": "RuntimeErrorWithCode"},
        )
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "core", f"Command failed: {exc}")
        typer.echo("ERROR: command failed (see logs)", err=True)
        exit_result = _runtime_error_result(
            catalog=ctx.catalog,
            command_name=command_name,
            message=str(exc),
            details={"runtime_error": exc.__class__.__name__},
        )
    finally:
        try:
            shutdown_result = _shutdown_container_resources(
                container=container,
                logger=logger,
                run_id=run_id,
                emit_user_error=exit_result is None,
            )
            if exit_result is None and shutdown_result is not None:
                exit_result = shutdown_result

            _ = getDurationMs(start_monotonic, time.monotonic())
            logEvent(logger, logging.INFO, run_id, "log", f"Log written: {log_file_path}")
        finally:
            sys.stdout = original_stdout
            sys.stderr = original_stderr

        if exit_result is not None:
            raise typer.Exit(code=_exit_code_from_result(exit_result))


def _bind_context_with_container(ctx: UnboundCommandContext, *, container: AppContainer) -> BoundCommandContext:
    return CommandContext(
        logger=ctx.logger,
        run_id=ctx.run_id,
        catalog=ctx.catalog,
        strict=ctx.strict,
        app_config=ctx.app_config,
        container=container,
        paths=ctx.paths,
        extra=ctx.extra,
    )


def _initialize_container_resources(
    *,
    container: AppContainer,
    requirements: Requirements,
    logger: logging.Logger,
    run_id: str,
) -> int | DomainCommandResult | CliCommandResult | None:
    try:
        _init_container_for_requirements(container, requirements)
    except DslLoadError:
        # Dictionary/DSL init failures must reach outer DSL error handling path unchanged.
        raise
    except sqlite3.Error as exc:
        logEvent(logger, logging.ERROR, run_id, "cache", f"Container cache init failed: {exc}")
        typer.echo("ERROR: failed to initialize cache resources (see logs/report)", err=True)
        return _result_with(SystemErrorCode.CACHE_ERROR)
    except VaultDomainError as exc:
        logEvent(logger, logging.ERROR, run_id, "vault", f"{exc.code}: {exc}")
        typer.echo(f"ERROR: {exc.code}: {exc}", err=True)
        return _result_with(SystemErrorCode.INTERNAL_ERROR)
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "core", f"Container resource init failed: {exc}")
        typer.echo("ERROR: failed to initialize runtime resources (see logs/report)", err=True)
        return _result_with(SystemErrorCode.INTERNAL_ERROR)
    return None


def _shutdown_container_resources(
    *,
    container: AppContainer | None,
    logger: logging.Logger,
    run_id: str,
    emit_user_error: bool,
) -> int | DomainCommandResult | CliCommandResult | None:
    if container is None:
        return None
    try:
        container.shutdown_resources()
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "core", f"Container shutdown failed: {exc}")
        if emit_user_error:
            typer.echo("ERROR: runtime teardown failed (see logs/report)", err=True)
        return _result_with(SystemErrorCode.INTERNAL_ERROR)
    return None


def _finalize_report_artifacts(
    *,
    report: ReportCollector,
    start_monotonic: float,
    paths,
    log_file_path: str,
    command_name: str,
    run_id: str,
    logger: logging.Logger,
    emit_user_error: bool,
) -> int | DomainCommandResult | CliCommandResult | None:
    try:
        duration_ms = getDurationMs(start_monotonic, time.monotonic())
        finalizeReport(
            report=report,
            durationMs=duration_ms,
            logFile=log_file_path,
            cacheDir=paths.cache_dir,
            reportDir=paths.report_dir,
        )
        report_path = writeReportJson(report, paths.report_dir, f"report_{command_name}_{run_id}")
        logEvent(logger, logging.INFO, run_id, "report", f"Report written: {report_path}")
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "report", f"Report finalization failed: {exc}")
        if emit_user_error:
            typer.echo("ERROR: failed to finalize report (see logs)", err=True)
        return _result_with(SystemErrorCode.INTERNAL_ERROR)
    return None


def _validate_requirements(ctx: CommandContext[Any], opts: Any, requirements: Requirements) -> None:
    """
    Назначение:
        Быстрые и предсказуемые проверки требований команды.
    """

    app_config = _require_app_settings(ctx)

    if requirements.requires_api:
        _require_api(app_config)

    dataset: str | None = None
    if requirements.requires_dataset or requirements.requires_source:
        dataset = _resolve_dataset_opt(opts, app_config)

    if requirements.requires_cache:
        _require_cache(app_config)

    if requirements.requires_secrets:
        vault_mode = _get_opt(opts, ("vault_mode",))
        _require_secrets(vault_mode)

    if requirements.requires_dataset:
        _require_dataset(dataset)
    if requirements.requires_source:
        _require_source(dataset)


def _require_source(dataset: str | None) -> None:
    if not dataset:
        raise RuntimeErrorWithCode("Dataset is required for source resolution", exit_code=2)
    try:
        source_spec = load_source_spec_for_dataset(dataset)
    except DslLoadError as exc:
        raise RuntimeErrorWithCode(
            f"Source spec is not configured for dataset '{dataset}': {exc.code}: {exc}",
            exit_code=2,
        ) from exc
    except Exception as exc:
        raise RuntimeErrorWithCode(f"Source spec is not configured for dataset '{dataset}': {exc}", exit_code=2) from exc
    try:
        location = resolve_source_location(source_spec)
    except DslLoadError as exc:
        raise RuntimeErrorWithCode(
            f"Source location is not configured for dataset '{dataset}': {exc.code}: {exc}",
            exit_code=2,
        ) from exc
    except ValueError as exc:
        raise RuntimeErrorWithCode(f"Source location is not configured for dataset '{dataset}': {exc}", exit_code=2) from exc
    if source_spec.source.type == "file":
        path = Path(location)
        if not path.exists() or not path.is_file():
            raise RuntimeErrorWithCode(f"Source file not found: {location}", exit_code=2)


def _require_api(app_config: AppConfig) -> None:
    api = app_config.api
    missing = []
    if not api.host:
        missing.append("host")
    if not api.port:
        missing.append("port")
    if not api.username:
        missing.append("api_username")
    if not api.password:
        missing.append("api_password")
    if missing:
        raise RuntimeErrorWithCode(f"Missing API settings: {', '.join(missing)}", exit_code=2)


def _require_cache(app_config: AppConfig) -> None:
    cache_dir = Path(app_config.paths.cache_dir)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeErrorWithCode(f"Cache dir not доступен: {exc}", exit_code=2) from exc


def _require_secrets(vault_mode: str | None) -> None:
    normalized = (vault_mode or "auto").strip().lower()
    if normalized == "off":
        raise RuntimeErrorWithCode("vault-mode=off is incompatible with command requirements", exit_code=2)


def _require_dataset(dataset: str | None) -> None:
    if not dataset:
        raise RuntimeErrorWithCode("Dataset is required", exit_code=2)
    try:
        _ = get_spec(dataset)
    except ValueError as exc:
        raise RuntimeErrorWithCode(str(exc), exit_code=2) from exc


def _call_handler(
    handler: ReportHandler,
    ctx: BoundCommandContext,
    opts: Any,
    report: ReportCollector | None,
) -> Any:
    """
    Назначение:
        Вызов handler с поддержкой двух контрактов:
        - handler(ctx, opts)
        - handler(ctx, opts, report)
    """
    sig = inspect.signature(handler)
    if len(sig.parameters) >= 3:
        return handler(ctx, opts, report)
    return handler(ctx, opts)


def _apply_cli_result_to_report(
    report: ReportCollector,
    result: Any,
    *,
    command_name: str,
    source: str,
    secondary: bool,
) -> None:
    """Назначение:
        Нормализовать runtime/handler результат в report items.

    Контракт:
        - Поддерживает оба формата результата (`DomainCommandResult` и legacy `CliCommandResult`).
        - Материализует synthetic diagnostics для non-OK результатов без явной диагностики.
        - Для secondary-ошибок понижает severity до warning, чтобы primary outcome оставался владельцем exit semantics.
    """
    if result is None:
        return

    if isinstance(result, CliCommandResult):
        _apply_legacy_cli_result(
            report=report,
            result=result,
            source=source,
            secondary=secondary,
        )
        return

    if isinstance(result, DomainCommandResult):
        _apply_domain_result(
            report=report,
            result=result,
            command_name=command_name,
            source=source,
            secondary=secondary,
        )
        return

    if isinstance(result, int):
        if result == 0:
            return
        severity = "warning" if secondary else "error"
        diagnostic = ReportDiagnostic(
            severity=severity,
            stage=_stage_for_command(command_name),
            code=f"EXIT_{result}",
            field=None,
            message=f"Command returned non-zero exit code: {result}",
            details={"exit_code": result},
        )
        errors, warnings = _with_secondary_policy(
            errors=[diagnostic] if severity == "error" else [],
            warnings=[diagnostic] if severity == "warning" else [],
            secondary=secondary,
        )
        report.add_item(
            status="FAILED" if errors else "OK",
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
    """Назначение:
        Поддержать legacy delivery `CliCommandResult` в едином runtime report pipeline.
    """
    for item in result.items:
        report_errors, report_warnings = split_report_diagnostics(item.get("errors"), item.get("warnings"))
        report_errors, report_warnings = _with_secondary_policy(
            errors=report_errors,
            warnings=report_warnings,
            secondary=secondary,
        )
        item_status = "FAILED" if report_errors else ("OK" if secondary else item.get("status", "OK"))
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
            status="FAILED" if report_errors else "OK",
            row_ref=None,
            payload=None,
            errors=report_errors,
            warnings=report_warnings,
            meta={"source": source, "secondary": secondary},
        )

    if result.stats:
        report.set_context("stats", result.stats)


def _apply_domain_result(
    *,
    report: ReportCollector,
    result: DomainCommandResult,
    command_name: str,
    source: str,
    secondary: bool,
) -> None:
    """Назначение:
        Перенести `DomainCommandResult` в report item с учётом synthetic fallback.
    """
    stage = _stage_for_command(command_name)
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
        status="FAILED" if errors else "OK",
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
    """Назначение:
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
    """Назначение:
        Определить warning-severity для DiagnosticItem/ReportDiagnostic в tolerant режиме.
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
    """Назначение:
        Применить политику secondary-error: demote error -> warning.
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
    """Назначение:
        Решить, нужен ли synthetic runtime diagnostic для non-OK результата без diagnostics.
    """
    if secondary:
        return True
    # Если row-level ошибки уже есть в отчёте, не дублируем их synthetic runtime-item.
    return report.summary.rows_blocked == 0 and report.summary.errors_total == 0


def _runtime_error_result(
    *,
    catalog,
    command_name: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> DomainCommandResult:
    """Назначение:
        Сконструировать `DomainCommandResult` для runtime-исключений с диагностикой.
    """
    stage = _stage_for_command(command_name)
    diagnostic = build_error(
        catalog=catalog,
        stage=stage,
        code="INTERNAL_ERROR",
        field=None,
        message=message,
        record_ref=None,
        details=details,
    )
    result = DomainCommandResult()
    result.add_diagnostics([diagnostic], catalog)
    return result


def _result_with(code: SystemErrorCode) -> DomainCommandResult:
    result = DomainCommandResult()
    result.add_code(code)
    return result


def _exit_code_from_result(result: Any) -> int:
    if result is None:
        return 0
    if hasattr(result, "exit_code"):
        return result.exit_code()
    if isinstance(result, int):
        return result
    if isinstance(result, CliCommandResult):
        if result.status == "ok":
            return 0
        if result.status == "warn":
            return 1
        return 2
    return 2


def _resolve_dataset_opt(opts: Any, app_config: AppConfig) -> str | None:
    dataset = _get_opt(opts, ("dataset", "dataset_name"))
    if dataset is None:
        return app_config.dataset.dataset_name
    return resolve_dataset_name(dataset, app_config.dataset.dataset_name)


def _get_opt(opts: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        if hasattr(opts, name):
            return getattr(opts, name)
    return None


def _config_sources(ctx: CommandContext[Any]) -> list[str]:
    extra = ctx.extra or {}
    sources = extra.get("sources") or extra.get("config_sources")
    return list(sources) if sources else []


def _require_app_settings(ctx: CommandContext[Any]) -> AppConfig:
    return ctx.app_config


def _echo_command_diagnostics(prefix: str, diagnostics: list[Any]) -> None:
    typer.echo(prefix, err=True)
    for diag in diagnostics:
        field = f" ({diag.field})" if getattr(diag, "field", None) else ""
        typer.echo(f"- [{diag.code}]{field} {diag.message}", err=True)


def _stage_for_command(command_name: str) -> DiagnosticStage:
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
