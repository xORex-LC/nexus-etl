from __future__ import annotations

import inspect
import logging
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

import typer

from connector.common.time import getDurationMs
from connector.domain.diagnostics.command_result import CommandResult as DomainCommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.reporting.diagnostics import split_report_diagnostics
from connector.domain.reporting.collector import ReportCollector
from connector.infra.artifacts.report_writer import createEmptyReport, finalizeReport, writeReportJson
from connector.infra.logging.setup import StdStreamToLogger, TeeStream, createCommandLogger, logEvent
from connector.datasets.registry import get_spec, resolve_dataset_name
from connector.delivery.cli.context import CommandContext
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli.result import CommandResult as CliCommandResult


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
    ctx: CommandContext,
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

    settings = ctx.settings
    run_id = ctx.run_id

    start_monotonic = time.monotonic()
    logger, log_file_path = createCommandLogger(
        commandName=command_name,
        logDir=settings.log_dir,
        runId=run_id,
        logLevel=settings.log_level,
    )
    ctx = replace(ctx, logger=logger)

    report = createEmptyReport(runId=run_id, command=command_name, configSources=_config_sources(ctx))

    csv_path = _get_opt(opts, ("csv_path", "csv", "input_csv"))
    if csv_path:
        report.set_context("input", {"csv_path": Path(csv_path).name})

    report_items_limit = _get_opt(opts, ("report_items_limit", "items_limit"))
    if report_items_limit is None:
        report_items_limit = settings.report_items_limit
    report.set_meta(items_limit=report_items_limit)

    dataset = _resolve_dataset_opt(opts, settings)
    if dataset is not None:
        report.set_meta(dataset=dataset)

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    stdout_logger_stream = StdStreamToLogger(logger, logging.INFO, run_id, "stdout")
    stderr_logger_stream = StdStreamToLogger(logger, logging.ERROR, run_id, "stderr")

    sys.stdout = TeeStream(original_stdout, stdout_logger_stream)
    sys.stderr = TeeStream(original_stderr, stderr_logger_stream)

    exit_result: int | DomainCommandResult | CliCommandResult | None = None

    try:
        logEvent(logger, logging.INFO, run_id, "core", "Command started")

        _validate_requirements(ctx, opts, requirements)

        exit_result = _call_handler(handler, ctx, opts, report)

        _apply_cli_result_to_report(report, exit_result)

    except RuntimeErrorWithCode as exc:
        logEvent(logger, logging.ERROR, run_id, "config", str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        exit_result = exc.exit_code
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "core", f"Command failed: {exc}")
        typer.echo("ERROR: command failed (see logs/report)", err=True)
        exit_result = _exit_code_from_result(_result_with(SystemErrorCode.INTERNAL_ERROR))
    finally:
        duration_ms = getDurationMs(start_monotonic, time.monotonic())
        finalizeReport(
            report=report,
            durationMs=duration_ms,
            logFile=log_file_path,
            cacheDir=settings.cache_dir,
            reportDir=settings.report_dir,
        )
        report_path = writeReportJson(report, settings.report_dir, f"report_{command_name}_{run_id}")
        logEvent(logger, logging.INFO, run_id, "report", f"Report written: {report_path}")

        sys.stdout = original_stdout
        sys.stderr = original_stderr

        if exit_result is not None:
            raise typer.Exit(code=_exit_code_from_result(exit_result))


def run_without_report(
    *,
    ctx: CommandContext,
    command_name: str,
    opts: Any,
    handler: ReportHandler,
    requirements: Requirements,
) -> None:
    """
    Назначение:
        Унифицированная обвязка выполнения команд без формирования отчёта.
    """

    settings = ctx.settings
    run_id = ctx.run_id

    start_monotonic = time.monotonic()
    logger, log_file_path = createCommandLogger(
        commandName=command_name,
        logDir=settings.log_dir,
        runId=run_id,
        logLevel=settings.log_level,
    )
    ctx = replace(ctx, logger=logger)

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    stdout_logger_stream = StdStreamToLogger(logger, logging.INFO, run_id, "stdout")
    stderr_logger_stream = StdStreamToLogger(logger, logging.ERROR, run_id, "stderr")

    sys.stdout = TeeStream(original_stdout, stdout_logger_stream)
    sys.stderr = TeeStream(original_stderr, stderr_logger_stream)

    exit_result: int | DomainCommandResult | CliCommandResult | None = None

    try:
        logEvent(logger, logging.INFO, run_id, "core", "Command started")

        _validate_requirements(ctx, opts, requirements)

        exit_result = _call_handler(handler, ctx, opts, None)

    except RuntimeErrorWithCode as exc:
        logEvent(logger, logging.ERROR, run_id, "config", str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        exit_result = exc.exit_code
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "core", f"Command failed: {exc}")
        typer.echo("ERROR: command failed (see logs)", err=True)
        exit_result = _exit_code_from_result(_result_with(SystemErrorCode.INTERNAL_ERROR))
    finally:
        _ = getDurationMs(start_monotonic, time.monotonic())
        logEvent(logger, logging.INFO, run_id, "log", f"Log written: {log_file_path}")

        sys.stdout = original_stdout
        sys.stderr = original_stderr

        if exit_result is not None:
            raise typer.Exit(code=_exit_code_from_result(exit_result))


def _validate_requirements(ctx: CommandContext, opts: Any, requirements: Requirements) -> None:
    """
    Назначение:
        Быстрые и предсказуемые проверки требований команды.
    """

    settings = ctx.settings

    if requirements.requires_api:
        _require_api(settings)

    if requirements.requires_csv:
        csv_path = _get_opt(opts, ("csv_path", "csv", "input_csv"))
        _require_csv(csv_path)

    if requirements.requires_cache:
        _require_cache(settings)

    if requirements.requires_secrets:
        vault_file = _get_opt(opts, ("vault_file", "vault", "secrets_file"))
        _require_secrets(vault_file)

    if requirements.requires_dataset:
        dataset = _resolve_dataset_opt(opts, settings)
        _require_dataset(dataset)


def _require_csv(csv_path: str | None) -> None:
    if not csv_path:
        raise RuntimeErrorWithCode("--csv is required", exit_code=2)
    path = Path(csv_path)
    if not path.exists() or not path.is_file():
        raise RuntimeErrorWithCode(f"CSV file not found: {csv_path}", exit_code=2)


def _require_api(settings) -> None:
    missing = []
    if not settings.host:
        missing.append("host")
    if not settings.port:
        missing.append("port")
    if not settings.api_username:
        missing.append("api_username")
    if not settings.api_password:
        missing.append("api_password")
    if missing:
        raise RuntimeErrorWithCode(f"Missing API settings: {', '.join(missing)}", exit_code=2)


def _require_cache(settings) -> None:
    cache_dir = Path(settings.cache_dir)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeErrorWithCode(f"Cache dir not доступен: {exc}", exit_code=2) from exc


def _require_secrets(vault_file: str | None) -> None:
    if not vault_file:
        raise RuntimeErrorWithCode("Vault file path is required", exit_code=2)
    path = Path(vault_file)
    if path.exists():
        return
    if path.parent:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeErrorWithCode(f"Vault dir not доступен: {exc}", exit_code=2) from exc


def _require_dataset(dataset: str | None) -> None:
    if not dataset:
        raise RuntimeErrorWithCode("Dataset is required", exit_code=2)
    try:
        _ = get_spec(dataset)
    except ValueError as exc:
        raise RuntimeErrorWithCode(str(exc), exit_code=2) from exc


def _call_handler(handler: ReportHandler, ctx: CommandContext, opts: Any, report: ReportCollector | None) -> Any:
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


def _apply_cli_result_to_report(report: ReportCollector, result: Any) -> None:
    """
    Назначение:
        Преобразует CommandResult (CLI) в элементы отчёта, если handler их вернул.
    """
    if not isinstance(result, CliCommandResult):
        return

    for item in result.items:
        report_errors, report_warnings = split_report_diagnostics(item.get("errors"), item.get("warnings"))
        report.add_item(
            status=item.get("status", "OK"),
            row_ref=item.get("row_ref"),
            payload=item.get("payload"),
            errors=report_errors,
            warnings=report_warnings,
            meta=item.get("meta"),
            store=item.get("store", True),
        )

    if result.errors or result.warnings:
        report_errors, report_warnings = split_report_diagnostics(result.errors, result.warnings)
        report.add_item(
            status="FAILED" if result.errors else "OK",
            row_ref=None,
            payload=None,
            errors=report_errors,
            warnings=report_warnings,
            meta={},
        )

    if result.stats:
        report.set_context("stats", result.stats)


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


def _resolve_dataset_opt(opts: Any, settings) -> str | None:
    dataset = _get_opt(opts, ("dataset", "dataset_name"))
    if dataset is None:
        return settings.dataset_name
    return resolve_dataset_name(dataset, settings.dataset_name)


def _get_opt(opts: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        if hasattr(opts, name):
            return getattr(opts, name)
    return None


def _config_sources(ctx: CommandContext) -> list[str]:
    extra = ctx.extra or {}
    sources = extra.get("sources") or extra.get("config_sources")
    return list(sources) if sources else []
