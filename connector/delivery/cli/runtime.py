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
from connector.domain.diagnostics.command_result import CommandResult as DomainCommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.dsl.diagnostics import translate_dsl_load_error
from connector.domain.dsl.issues import DslLoadError
from connector.domain.reporting.diagnostics import split_report_diagnostics
from connector.domain.reporting.collector import ReportCollector
from connector.domain.secrets.errors import VaultDomainError
from connector.infra.artifacts.report_writer import createEmptyReport, finalizeReport, writeReportJson
from connector.infra.logging.setup import StdStreamToLogger, TeeStream, createCommandLogger, logEvent
from connector.datasets.registry import get_spec, resolve_dataset_name
from connector.domain.transform_dsl import load_source_spec_for_dataset, resolve_source_location
from connector.delivery.cli.containers import AppContainer, _init_container_for_requirements
from connector.delivery.cli.context import BoundCommandContext, CommandContext, UnboundCommandContext
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli.result import CommandResult as CliCommandResult
from connector.domain.models import DiagnosticStage


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
        else:
            bound_ctx = _bind_context_with_container(ctx, container=container)
            exit_result = _call_handler(handler, bound_ctx, opts, report)
            _apply_cli_result_to_report(report, exit_result)

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
        report_errors, report_warnings = split_report_diagnostics(diags, [])
        report.add_item(
            status="FAILED",
            row_ref=None,
            payload=None,
            errors=report_errors,
            warnings=report_warnings,
            meta={"exception": "SettingsLoadError"},
        )
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
        report_errors, report_warnings = split_report_diagnostics([diag], [])
        report.add_item(
            status="FAILED",
            row_ref=None,
            payload=None,
            errors=report_errors,
            warnings=report_warnings,
            meta={"exception": "DslLoadError", "code": exc.code},
        )
        result = DomainCommandResult()
        result.add_diagnostics([diag], ctx.catalog)
        exit_result = result
    except RuntimeErrorWithCode as exc:
        logEvent(logger, logging.ERROR, run_id, "config", str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        exit_result = exc.exit_code
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "core", f"Command failed: {exc}")
        typer.echo("ERROR: command failed (see logs/report)", err=True)
        exit_result = _exit_code_from_result(_result_with(SystemErrorCode.INTERNAL_ERROR))
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
        exit_result = exc.exit_code
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "core", f"Command failed: {exc}")
        typer.echo("ERROR: command failed (see logs)", err=True)
        exit_result = _exit_code_from_result(_result_with(SystemErrorCode.INTERNAL_ERROR))
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
