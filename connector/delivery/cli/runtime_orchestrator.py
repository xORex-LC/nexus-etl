"""
Назначение:
    CLI runtime orchestration (init -> handler -> finalize -> shutdown).

Граница ответственности:
    - Владеет lifecycle-оркестрацией и handler invocation contract.
    - Не содержит result-to-report mapping правил (runtime_result_mapper owner).
    - Не знает о legacy result форматах (result_adapter owner).
"""

from __future__ import annotations

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
from connector.domain.dsl.diagnostics import translate_dsl_load_error
from connector.domain.dsl.issues import DslLoadError
from connector.domain.reporting.assembler import ReportAssembler
from connector.domain.reporting.context import InMemoryReportContext
from connector.domain.reporting.contracts import ReportContextKey
from connector.domain.reporting.events import FinishEvent, SetContextEvent, SetMetaEvent
from connector.domain.reporting.policy import ReportPolicy
from connector.domain.reporting.sink import NullReportSink, ReportSink
from connector.domain.secrets.errors import VaultDomainError
from connector.infra.artifacts.report_renderer import JsonReportRenderer
from connector.infra.logging.setup import StdStreamToLogger, TeeStream, createCommandLogger, logEvent
from connector.datasets.registry import get_spec, resolve_dataset_name
from connector.domain.transform_dsl import load_source_spec_for_dataset, resolve_source_location
from connector.delivery.cli.context import BoundCommandContext, CommandContext, UnboundCommandContext
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli.containers import AppContainer
from connector.delivery.cli.runtime_contracts import (
    CommandHandler,
    RuntimeErrorWithCode,
    RuntimeExecutionResult,
)
from connector.delivery.cli.runtime_result_mapper import (
    build_runtime_error_result,
    stage_for_command,
)

from connector.domain.diagnostics.policies import SystemErrorCode
from connector.delivery.cli.result_adapter import result_with


def run_with_report(
    *,
    ctx: UnboundCommandContext,
    command_name: str,
    opts: Any,
    handler: CommandHandler,
    requirements: Requirements,
    create_container: Callable[[], AppContainer],
    initialize_container_resources: Callable[..., RuntimeExecutionResult],
    shutdown_container_resources: Callable[..., RuntimeExecutionResult],
    finalize_report_artifacts: Callable[..., RuntimeExecutionResult],
    apply_result_to_report: Callable[..., None],
    exit_code_from_result: Callable[[Any], int],
) -> None:
    """
    Назначение:
        Унифицированная обвязка выполнения команд с report lifecycle.

    Контракт:
        - Handler вызывается строго с тремя аргументами `(ctx, opts, report_sink)`.
        - Result-to-report mapping выполняется через injected mapper.
    """
    app_config = require_app_settings(ctx)
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

    report_context = InMemoryReportContext(run_id=run_id, command=command_name)
    report_sink = ReportSink(report_context)
    report_assembler = ReportAssembler(context=report_context)
    sources = config_sources(ctx)
    if sources:
        report_sink.emit(SetContextEvent(name=ReportContextKey.CONFIG, value={"sources": sources}))
    report_policy = ReportPolicy.from_profile(app_config.observability.report_policy_profile)
    cli_include_skipped_raw = get_opt(opts, ("report_include_skipped",))
    cli_include_skipped = (
        app_config.observability.report_include_skipped
        if cli_include_skipped_raw is None
        else bool(cli_include_skipped_raw)
    )
    effective_include_skipped_items = report_policy.resolve_include_skipped_items(cli_include_skipped)
    report_sink.emit(
        SetContextEvent(
            name=ReportContextKey.REPORT_POLICY,
            value=report_policy.to_context_payload(
                cli_include_skipped=cli_include_skipped,
                effective_include_skipped_items=effective_include_skipped_items,
            ),
        )
    )

    csv_path = get_opt(opts, ("csv_path", "csv", "input_csv"))
    if csv_path:
        report_sink.emit(SetContextEvent(name=ReportContextKey.INPUT, value={"csv_path": Path(csv_path).name}))

    report_items_limit = get_opt(opts, ("report_items_limit", "items_limit"))
    if report_items_limit is None:
        report_items_limit = observability.report_items_limit
    report_sink.emit(SetMetaEvent(items_limit=report_items_limit))

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    stdout_logger_stream = StdStreamToLogger(logger, logging.INFO, run_id, "stdout")
    stderr_logger_stream = StdStreamToLogger(logger, logging.ERROR, run_id, "stderr")

    sys.stdout = TeeStream(original_stdout, stdout_logger_stream)
    sys.stderr = TeeStream(original_stderr, stderr_logger_stream)

    exit_result: RuntimeExecutionResult = None
    container: AppContainer | None = None

    try:
        logEvent(logger, logging.INFO, run_id, "core", "Command started")

        validate_requirements(ctx, opts, requirements)

        container = create_container()
        container.app_config.override(app_config)
        api_transport = get_opt(opts, ("api_transport",))
        if api_transport is not None:
            container.target.transport.override(api_transport)
        init_result = initialize_container_resources(
            container=container,
            requirements=requirements,
            logger=logger,
            run_id=run_id,
        )
        if init_result is not None:
            exit_result = init_result
            apply_result_to_report(
                report_sink,
                report_context,
                exit_result,
                command_name=command_name,
                source="runtime_init",
                secondary=False,
            )
        else:
            bound_ctx = bind_context_with_container(ctx, container=container)
            exit_result = handler(bound_ctx, opts, report_sink)
            apply_result_to_report(
                report_sink,
                report_context,
                exit_result,
                command_name=command_name,
                source="handler_result",
                secondary=False,
            )

    except SettingsLoadError as exc:
        stage = stage_for_command(command_name)
        diags = translate_settings_load_error(
            catalog=ctx.catalog,
            stage=stage,
            error=exc,
            record_ref=None,
        )
        logEvent(logger, logging.ERROR, run_id, "config", f"Settings error: {exc}")
        echo_command_diagnostics("ERROR: invalid settings configuration", diags)
        result = DomainCommandResult()
        result.add_diagnostics(diags, ctx.catalog)
        exit_result = result
        apply_result_to_report(
            report_sink,
            report_context,
            exit_result,
            command_name=command_name,
            source="settings_load_error",
            secondary=False,
        )
    except DslLoadError as exc:
        stage = stage_for_command(command_name)
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
        apply_result_to_report(
            report_sink,
            report_context,
            exit_result,
            command_name=command_name,
            source="dsl_load_error",
            secondary=False,
        )
    except RuntimeErrorWithCode as exc:
        logEvent(logger, logging.ERROR, run_id, "config", str(exc))
        typer.echo(f"ERROR: {exc}", err=True)
        exit_result = build_runtime_error_result(
            catalog=ctx.catalog,
            command_name=command_name,
            message=str(exc),
            details={"runtime_exit_code": exc.exit_code, "runtime_error": "RuntimeErrorWithCode"},
        )
        apply_result_to_report(
            report_sink,
            report_context,
            exit_result,
            command_name=command_name,
            source="runtime_validation_error",
            secondary=False,
        )
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "core", f"Command failed: {exc}")
        typer.echo("ERROR: command failed (see logs/report)", err=True)
        exit_result = build_runtime_error_result(
            catalog=ctx.catalog,
            command_name=command_name,
            message=str(exc),
            details={"runtime_error": exc.__class__.__name__},
        )
        apply_result_to_report(
            report_sink,
            report_context,
            exit_result,
            command_name=command_name,
            source="runtime_exception",
            secondary=False,
        )
    finally:
        try:
            shutdown_result = shutdown_container_resources(
                container=container,
                logger=logger,
                run_id=run_id,
                emit_user_error=exit_result is None,
            )
            if shutdown_result is not None:
                apply_result_to_report(
                    report_sink,
                    report_context,
                    shutdown_result,
                    command_name=command_name,
                    source="runtime_shutdown",
                    secondary=exit_result is not None,
                )
            if exit_result is None and shutdown_result is not None:
                exit_result = shutdown_result

            finalize_result = finalize_report_artifacts(
                report_sink=report_sink,
                report_assembler=report_assembler,
                start_monotonic=start_monotonic,
                paths=paths,
                log_file_path=log_file_path,
                command_name=command_name,
                run_id=run_id,
                logger=logger,
                emit_user_error=exit_result is None,
            )
            if finalize_result is not None:
                apply_result_to_report(
                    report_sink,
                    report_context,
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
            raise typer.Exit(code=exit_code_from_result(exit_result))


def run_without_report(
    *,
    ctx: UnboundCommandContext,
    command_name: str,
    opts: Any,
    handler: CommandHandler,
    requirements: Requirements,
    create_container: Callable[[], AppContainer],
    initialize_container_resources: Callable[..., RuntimeExecutionResult],
    shutdown_container_resources: Callable[..., RuntimeExecutionResult],
    exit_code_from_result: Callable[[Any], int],
) -> None:
    """
    Назначение:
        Унифицированная обвязка выполнения команд без рендеринга report.

    Контракт:
        Handler вызывается по тому же 3-arg контракту с `NullReportSink`.
    """
    app_config = require_app_settings(ctx)
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

    exit_result: RuntimeExecutionResult = None
    container: AppContainer | None = None

    try:
        logEvent(logger, logging.INFO, run_id, "core", "Command started")

        validate_requirements(ctx, opts, requirements)

        container = create_container()
        container.app_config.override(app_config)
        api_transport = get_opt(opts, ("api_transport",))
        if api_transport is not None:
            container.target.transport.override(api_transport)
        init_result = initialize_container_resources(
            container=container,
            requirements=requirements,
            logger=logger,
            run_id=run_id,
        )
        if init_result is not None:
            exit_result = init_result
        else:
            bound_ctx = bind_context_with_container(ctx, container=container)
            exit_result = handler(bound_ctx, opts, NullReportSink())

    except SettingsLoadError as exc:
        stage = stage_for_command(command_name)
        diags = translate_settings_load_error(
            catalog=ctx.catalog,
            stage=stage,
            error=exc,
            record_ref=None,
        )
        logEvent(logger, logging.ERROR, run_id, "config", f"Settings error: {exc}")
        echo_command_diagnostics("ERROR: invalid settings configuration", diags)
        result = DomainCommandResult()
        result.add_diagnostics(diags, ctx.catalog)
        exit_result = result
    except DslLoadError as exc:
        stage = stage_for_command(command_name)
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
        exit_result = build_runtime_error_result(
            catalog=ctx.catalog,
            command_name=command_name,
            message=str(exc),
            details={"runtime_exit_code": exc.exit_code, "runtime_error": "RuntimeErrorWithCode"},
        )
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "core", f"Command failed: {exc}")
        typer.echo("ERROR: command failed (see logs)", err=True)
        exit_result = build_runtime_error_result(
            catalog=ctx.catalog,
            command_name=command_name,
            message=str(exc),
            details={"runtime_error": exc.__class__.__name__},
        )
    finally:
        try:
            shutdown_result = shutdown_container_resources(
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
            raise typer.Exit(code=exit_code_from_result(exit_result))


def bind_context_with_container(ctx: UnboundCommandContext, *, container: AppContainer) -> BoundCommandContext:
    """
    Назначение:
        Привязать command-context к инициализированному DI container.
    """
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


def initialize_container_resources(
    *,
    container: AppContainer,
    requirements: Requirements,
    logger: logging.Logger,
    run_id: str,
    init_container_for_requirements: Callable[[AppContainer, Requirements], None],
) -> RuntimeExecutionResult:
    """
    Назначение:
        Инициализировать DI ресурсы под runtime requirements.
    """
    try:
        init_container_for_requirements(container, requirements)
    except DslLoadError:
        # Dictionary/DSL init failures must reach outer DSL error handling path unchanged.
        raise
    except sqlite3.Error as exc:
        logEvent(logger, logging.ERROR, run_id, "cache", f"Container cache init failed: {exc}")
        typer.echo("ERROR: failed to initialize cache resources (see logs/report)", err=True)
        return result_with(SystemErrorCode.CACHE_ERROR)
    except VaultDomainError as exc:
        logEvent(logger, logging.ERROR, run_id, "vault", f"{exc.code}: {exc}")
        typer.echo(f"ERROR: {exc.code}: {exc}", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "core", f"Container resource init failed: {exc}")
        typer.echo("ERROR: failed to initialize runtime resources (see logs/report)", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    return None


def shutdown_container_resources(
    *,
    container: AppContainer | None,
    logger: logging.Logger,
    run_id: str,
    emit_user_error: bool,
) -> RuntimeExecutionResult:
    """
    Назначение:
        Graceful shutdown DI ресурсов с runtime->result mapping.
    """
    if container is None:
        return None
    try:
        container.shutdown_resources()
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "core", f"Container shutdown failed: {exc}")
        if emit_user_error:
            typer.echo("ERROR: runtime teardown failed (see logs/report)", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    return None


def finalize_report_artifacts(
    *,
    report_sink,
    report_assembler: ReportAssembler,
    start_monotonic: float,
    paths,
    log_file_path: str,
    command_name: str,
    run_id: str,
    logger: logging.Logger,
    emit_user_error: bool,
) -> RuntimeExecutionResult:
    """
    Назначение:
        Финализировать report envelope и записать JSON artifact.
    """
    try:
        duration_ms = getDurationMs(start_monotonic, time.monotonic())
        report_sink.emit(
            SetContextEvent(
                name=ReportContextKey.RUNTIME,
                value={
                    "log_file": log_file_path,
                    "cache_dir": paths.cache_dir,
                    "report_dir": paths.report_dir,
                },
            )
        )
        report_sink.emit(FinishEvent(duration_ms=duration_ms))
        envelope = report_assembler.assemble()
        report_path = JsonReportRenderer().render(
            envelope=envelope,
            report_dir=paths.report_dir,
            file_base_name=f"report_{command_name}_{run_id}",
        )
        logEvent(logger, logging.INFO, run_id, "report", f"Report written: {report_path}")
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "report", f"Report finalization failed: {exc}")
        if emit_user_error:
            typer.echo("ERROR: failed to finalize report (see logs)", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    return None


def validate_requirements(ctx: CommandContext[Any], opts: Any, requirements: Requirements) -> None:
    """
    Назначение:
        Быстрые и предсказуемые проверки требований команды.
    """
    app_config = require_app_settings(ctx)

    if requirements.requires_api:
        require_api(app_config)

    dataset: str | None = None
    if requirements.requires_dataset or requirements.requires_source:
        dataset = resolve_dataset_opt(opts, app_config)

    if requirements.requires_cache:
        require_cache(app_config)

    if requirements.requires_secrets:
        vault_mode = get_opt(opts, ("vault_mode",))
        require_secrets(vault_mode)

    if requirements.requires_dataset:
        require_dataset(dataset)
    if requirements.requires_source:
        require_source(dataset)


def require_source(dataset: str | None) -> None:
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


def require_api(app_config: AppConfig) -> None:
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


def require_cache(app_config: AppConfig) -> None:
    cache_dir = Path(app_config.paths.cache_dir)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeErrorWithCode(f"Cache dir not доступен: {exc}", exit_code=2) from exc


def require_secrets(vault_mode: str | None) -> None:
    normalized = (vault_mode or "auto").strip().lower()
    if normalized == "off":
        raise RuntimeErrorWithCode("vault-mode=off is incompatible with command requirements", exit_code=2)


def require_dataset(dataset: str | None) -> None:
    if not dataset:
        raise RuntimeErrorWithCode("Dataset is required", exit_code=2)
    try:
        _ = get_spec(dataset)
    except ValueError as exc:
        raise RuntimeErrorWithCode(str(exc), exit_code=2) from exc


def resolve_dataset_opt(opts: Any, app_config: AppConfig) -> str | None:
    dataset = get_opt(opts, ("dataset", "dataset_name"))
    if dataset is None:
        return app_config.dataset.dataset_name
    return resolve_dataset_name(dataset, app_config.dataset.dataset_name)


def get_opt(opts: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        if hasattr(opts, name):
            return getattr(opts, name)
    return None


def config_sources(ctx: CommandContext[Any]) -> list[str]:
    extra = ctx.extra or {}
    sources = extra.get("sources") or extra.get("config_sources")
    return list(sources) if sources else []


def require_app_settings(ctx: CommandContext[Any]) -> AppConfig:
    return ctx.app_config


def echo_command_diagnostics(prefix: str, diagnostics: list[Any]) -> None:
    typer.echo(prefix, err=True)
    for diag in diagnostics:
        field = f" ({diag.field})" if getattr(diag, "field", None) else ""
        typer.echo(f"- [{diag.code}]{field} {diag.message}", err=True)


__all__ = [
    "bind_context_with_container",
    "config_sources",
    "echo_command_diagnostics",
    "finalize_report_artifacts",
    "get_opt",
    "initialize_container_resources",
    "require_app_settings",
    "require_cache",
    "require_dataset",
    "require_secrets",
    "require_source",
    "resolve_dataset_opt",
    "run_with_report",
    "run_without_report",
    "shutdown_container_resources",
    "validate_requirements",
]
