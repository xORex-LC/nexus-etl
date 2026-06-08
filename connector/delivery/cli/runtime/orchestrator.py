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
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import typer
import structlog

from connector.common.time import get_duration_ms, get_now_iso
from connector.config.config import SettingsLoadError
from connector.config.models import AppConfig
from connector.config.diagnostics import translate_settings_load_error
from connector.config.projections import to_observability_layout, to_operational_paths
from connector.domain.diagnostics.command_result import (
    CommandResult as DomainCommandResult,
)
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
from connector.common.observability import (
    ObservabilityArtifactKind,
    ObservabilityLayout,
    ServiceComponent,
)
from connector.delivery.cli.stream_capture import StdStreamToLogger, TeeStream
from connector.delivery.cli.component_mapping import component_for_command
from connector.infra.logging.runtime import (
    _LOG_SCHEMA_VERSION,
    StructuredLoggingRuntime,
    bind_observability_context,
    clear_observability_context,
)
from connector.infra.observability.ledger import (
    RunLedgerRowCounters,
    build_run_ledger_record,
)
from connector.datasets.registry import get_spec, resolve_dataset_name
from connector.domain.transform_dsl import (
    load_source_spec_for_dataset,
    resolve_source_location,
)
from connector.delivery.cli.context import (
    BoundCommandContext,
    CommandContext,
    UnboundCommandContext,
)
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli.containers import AppContainer
from .contracts import (
    CommandHandler,
    RuntimeErrorWithCode,
    RuntimeExecutionResult,
)
from .result_mapper import (
    build_runtime_error_result,
    stage_for_command,
)

from connector.domain.diagnostics.policies import SystemErrorCode
from .result_adapter import result_with
from connector.usecases.topology_bootstrap import TOPOLOGY_PIPELINE_COMMANDS
from .topology_bootstrap import (
    TopologyBootstrapStep,
    TopologyBootstrapStepResult,
    attach_topology_runtime,
)

_RESOURCE_SHUTDOWN_CONTAINERS = (
    "target",
    "dictionary",
    "cache",
    "sqlite",
)
"""Subcontainers, owning Resource providers that must be closed before report finalization.

Why these four:
    - `target`, `dictionary`, `cache`, `sqlite` currently own runtime `Resource` providers.
    - `vault` and `pipeline` do not declare `Resource` providers; they depend on upstream
      sqlite/cache resources and therefore do not participate in explicit shutdown here.
    - `observability` is intentionally excluded and closed separately as the final step via
      `close_observability_runtime()`, so finalization/ledger/pointer logs remain observable.
"""


def _add_bootstrap_schema_version(
    _logger: Any, _method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    event_dict.setdefault("schema_version", _LOG_SCHEMA_VERSION)
    return event_dict


def _build_bootstrap_logger(
    *,
    command_name: str,
    run_id: str,
    pipeline_run_id: str,
    component: ServiceComponent,
    dataset: str | None,
    stderr_stream,
) -> Any:
    """Создать stderr-bound logger для ошибок до инициализации logging runtime."""
    fields: dict[str, Any] = {
        "run_id": run_id,
        "pipeline_run_id": pipeline_run_id,
        "component": component.value,
    }
    if dataset is not None:
        fields["dataset"] = dataset
    return structlog.wrap_logger(
        structlog.PrintLogger(stderr_stream),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_bootstrap_schema_version,
            structlog.processors.JSONRenderer(),
        ],
        cache_logger_on_first_use=False,
    ).bind(**fields)


@dataclass(frozen=True)
class RuntimeObservabilitySession:
    """Собрать observability-зависимости одного command execution lifecycle.

    Сессия живёт только внутри runtime orchestration и связывает вместе
    service-component, чистый artifact layout и активный structlog runtime.
    Она не владеет teardown: закрытие остаётся за DI `Resource`.
    """

    component: ServiceComponent
    layout: ObservabilityLayout
    runtime: StructuredLoggingRuntime
    logger: Any
    log_file_path: str | None


def _resolve_command_dataset(
    *,
    command_name: str,
    opts: Any,
    app_config: AppConfig,
) -> str | None:
    """Разрешить dataset для bind-contextvars, если команда dataset-aware."""
    if command_name in {
        "check-api",
        "vault-management-init",
        "vault-management-status",
        "vault-management-rotate",
        "vault-management-rewrap",
    }:
        return None
    return resolve_dataset_opt(opts, app_config)


def _initialize_observability_session(
    *,
    container: AppContainer,
    command_name: str,
    stderr_stream,
) -> RuntimeObservabilitySession:
    """Инициализировать observability runtime через DI container."""
    component = component_for_command(command_name)
    container.observability.component.override(component)
    container.observability.stderr_stream.override(stderr_stream)
    container.observability.logging_runtime.init()
    runtime = container.observability.logging_runtime()
    layout = container.observability.observability_layout()
    logger = runtime.get_logger(
        component,
        logger_name=f"nexus.{component.value}.{command_name}",
    )
    return RuntimeObservabilitySession(
        component=component,
        layout=layout,
        runtime=runtime,
        logger=logger,
        log_file_path=runtime.current_log_file_path(),
    )


def _run_observability_sweeper(
    *,
    container: AppContainer,
    app_config: AppConfig,
    session: RuntimeObservabilitySession,
    logger: Any,
) -> None:
    """Выполнить best-effort sweep observability-артефактов на старте команды."""
    sweeper = container.observability.sweeper()
    try:
        if app_config.observability.logging.sinks.file.enabled:
            sweeper.sweep_logs(
                component=session.component,
                retention_days=app_config.observability.logging.sinks.file.retention_days,
                retention_backups=app_config.observability.logging.sinks.file.retention_backups,
            )
        sweeper.sweep_reports(
            component=session.component,
            retention_days=app_config.observability.reporting.retention_days,
        )
        sweeper.sweep_plans(
            component=session.component,
            retention_days=app_config.observability.plans.retention_days,
        )
        if app_config.observability.ledger.enabled:
            sweeper.sweep_ledger(
                component=session.component,
                retention_days=app_config.observability.logging.sinks.file.retention_days,
            )
    except Exception as exc:
        logger.warning(
            "Observability sweep failed",
            scope="observability",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )


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
    run_topology_bootstrap: Callable[..., TopologyBootstrapStepResult] | None = None,
) -> None:
    """
    Назначение:
        Унифицированная обвязка выполнения команд с report lifecycle.

    Контракт:
        - Handler вызывается строго с тремя аргументами `(ctx, opts, report_sink)`.
        - Result-to-report mapping выполняется через injected mapper.
    """
    app_config = require_app_settings(ctx)
    paths = to_operational_paths(app_config)
    observability = app_config.observability
    run_id = ctx.run_id
    pipeline_run_id = ctx.pipeline_run_id or run_id
    dataset_name = _resolve_command_dataset(
        command_name=command_name,
        opts=opts,
        app_config=app_config,
    )
    run_topology_bootstrap = run_topology_bootstrap or _run_topology_bootstrap_if_needed

    start_monotonic = time.monotonic()
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    report_context = InMemoryReportContext(run_id=run_id, command=command_name)
    report_sink = ReportSink(report_context)
    report_assembler = ReportAssembler(context=report_context)
    sources = config_sources(ctx)
    if sources:
        report_sink.emit(
            SetContextEvent(name=ReportContextKey.CONFIG, value={"sources": sources})
        )
    report_policy = ReportPolicy.from_profile(
        app_config.observability.reporting.policy_profile
    )
    fallback_component = component_for_command(command_name)
    fallback_layout = to_observability_layout(app_config)
    report_started_at = report_context.meta_snapshot().started_at
    cli_include_skipped_raw = get_opt(opts, ("report_include_skipped",))
    cli_include_skipped = (
        app_config.observability.reporting.include_skipped
        if cli_include_skipped_raw is None
        else bool(cli_include_skipped_raw)
    )
    effective_include_skipped_items = report_policy.resolve_include_skipped_items(
        cli_include_skipped
    )
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
        report_sink.emit(
            SetContextEvent(
                name=ReportContextKey.INPUT, value={"csv_path": Path(csv_path).name}
            )
        )

    report_items_limit = get_opt(opts, ("report_items_limit", "items_limit"))
    if report_items_limit is None:
        report_items_limit = observability.reporting.items_limit
    report_sink.emit(SetMetaEvent(items_limit=report_items_limit))

    exit_result: RuntimeExecutionResult = None
    container: AppContainer | None = None
    observability_session: RuntimeObservabilitySession | None = None
    logger: Any = _build_bootstrap_logger(
        command_name=command_name,
        run_id=run_id,
        pipeline_run_id=pipeline_run_id,
        component=fallback_component,
        dataset=dataset_name,
        stderr_stream=original_stderr,
    )
    log_file_path: str | None = None

    try:
        container = create_container()
        container.app_config.override(app_config)
        api_transport = get_opt(opts, ("api_transport",))
        if api_transport is not None:
            container.target.transport.override(api_transport)

        observability_session = _initialize_observability_session(
            container=container,
            command_name=command_name,
            stderr_stream=original_stderr,
        )
        logger = observability_session.logger
        log_file_path = observability_session.log_file_path
        ctx = replace(ctx, logger=logger)
        bind_observability_context(
            run_id=run_id,
            pipeline_run_id=pipeline_run_id,
            component=observability_session.component,
            dataset=dataset_name,
        )
        _run_observability_sweeper(
            container=container,
            app_config=app_config,
            session=observability_session,
            logger=logger,
        )
        interactive_io_gate = container.observability.interactive_io_gate()

        stdout_logger_stream = StdStreamToLogger(
            logger,
            logging.INFO,
            "stdout",
            redaction_engine=observability_session.runtime.redaction_engine,
            interactive_io_gate=interactive_io_gate,
        )
        stderr_logger_stream = StdStreamToLogger(
            logger,
            logging.ERROR,
            "stderr",
            redaction_engine=observability_session.runtime.redaction_engine,
            interactive_io_gate=interactive_io_gate,
        )
        sys.stdout = TeeStream(original_stdout, stdout_logger_stream)
        sys.stderr = TeeStream(original_stderr, stderr_logger_stream)

        logger.info("Command started", scope="core")

        validate_requirements(ctx, opts, requirements)

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
            topology_step_result = run_topology_bootstrap(
                ctx=ctx,
                command_name=command_name,
                opts=opts,
                requirements=requirements,
                container=container,
                report_sink=report_sink,
                logger=logger,
                run_id=run_id,
            )
            ctx = attach_topology_runtime(
                ctx=ctx,
                runtime_binding=topology_step_result.runtime_binding,
            )
            if topology_step_result.command_result is not None:
                exit_result = topology_step_result.command_result
                apply_result_to_report(
                    report_sink,
                    report_context,
                    exit_result,
                    command_name=command_name,
                    source="topology_bootstrap",
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
        logger.error(
            "Settings error",
            scope="config",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
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
        logger.error(
            "DSL load error",
            scope="dsl",
            diag_code=exc.code,
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
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
        logger.error(
            "Runtime validation error",
            scope="config",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
        typer.echo(f"ERROR: {exc}", err=True)
        exit_result = build_runtime_error_result(
            catalog=ctx.catalog,
            command_name=command_name,
            message=str(exc),
            details={
                "runtime_exit_code": exc.exit_code,
                "runtime_error": "RuntimeErrorWithCode",
            },
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
        logger.error(
            "Command failed",
            scope="core",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
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
            sys.stdout = original_stdout
            sys.stderr = original_stderr
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
            active_layout = (
                observability_session.layout
                if observability_session is not None
                else fallback_layout
            )
            active_component = (
                observability_session.component
                if observability_session is not None
                else fallback_component
            )
            finalize_result = finalize_report_artifacts(
                report_sink=report_sink,
                report_assembler=report_assembler,
                start_monotonic=start_monotonic,
                paths=paths,
                log_file_path=log_file_path,
                command_name=command_name,
                run_id=run_id,
                logger=logger,
                layout=active_layout,
                component=active_component,
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
            _publish_latest_artifact_pointers_for_report(
                container=container,
                component=active_component,
                layout=active_layout,
                report_assembler=report_assembler,
                logger=logger,
                run_id=run_id,
                log_file_path=log_file_path,
                plan_path=_resolve_runtime_plan_path(ctx=ctx, opts=opts),
            )
            _record_run_ledger_for_report(
                container=container,
                enabled=app_config.observability.ledger.enabled,
                component=active_component,
                layout=active_layout,
                report_assembler=report_assembler,
                logger=logger,
                run_id=run_id,
                pipeline_run_id=pipeline_run_id,
                started_at=report_started_at,
                log_file_path=log_file_path,
                plan_path=_resolve_runtime_plan_path(ctx=ctx, opts=opts),
                final_result=exit_result,
                exit_code_from_result=exit_code_from_result,
            )
        finally:
            close_observability_runtime(container)
            clear_observability_context()

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
    run_topology_bootstrap: Callable[..., TopologyBootstrapStepResult] | None = None,
) -> None:
    """
    Назначение:
        Унифицированная обвязка выполнения команд без рендеринга report.

    Контракт:
        Handler вызывается по тому же 3-arg контракту с `NullReportSink`.
    """
    app_config = require_app_settings(ctx)
    run_id = ctx.run_id
    pipeline_run_id = ctx.pipeline_run_id or run_id
    dataset_name = _resolve_command_dataset(
        command_name=command_name,
        opts=opts,
        app_config=app_config,
    )
    fallback_component = component_for_command(command_name)
    run_topology_bootstrap = run_topology_bootstrap or _run_topology_bootstrap_if_needed

    start_monotonic = time.monotonic()
    started_at = get_now_iso()
    original_stdout = sys.stdout
    original_stderr = sys.stderr

    exit_result: RuntimeExecutionResult = None
    container: AppContainer | None = None
    observability_session: RuntimeObservabilitySession | None = None
    logger: Any = _build_bootstrap_logger(
        command_name=command_name,
        run_id=run_id,
        pipeline_run_id=pipeline_run_id,
        component=fallback_component,
        dataset=dataset_name,
        stderr_stream=original_stderr,
    )
    log_file_path: str | None = None

    try:
        container = create_container()
        container.app_config.override(app_config)
        api_transport = get_opt(opts, ("api_transport",))
        if api_transport is not None:
            container.target.transport.override(api_transport)

        observability_session = _initialize_observability_session(
            container=container,
            command_name=command_name,
            stderr_stream=original_stderr,
        )
        logger = observability_session.logger
        log_file_path = observability_session.log_file_path
        ctx = replace(ctx, logger=logger)
        bind_observability_context(
            run_id=run_id,
            pipeline_run_id=pipeline_run_id,
            component=observability_session.component,
            dataset=dataset_name,
        )
        _run_observability_sweeper(
            container=container,
            app_config=app_config,
            session=observability_session,
            logger=logger,
        )
        interactive_io_gate = container.observability.interactive_io_gate()

        stdout_logger_stream = StdStreamToLogger(
            logger,
            logging.INFO,
            "stdout",
            redaction_engine=observability_session.runtime.redaction_engine,
            interactive_io_gate=interactive_io_gate,
        )
        stderr_logger_stream = StdStreamToLogger(
            logger,
            logging.ERROR,
            "stderr",
            redaction_engine=observability_session.runtime.redaction_engine,
            interactive_io_gate=interactive_io_gate,
        )
        sys.stdout = TeeStream(original_stdout, stdout_logger_stream)
        sys.stderr = TeeStream(original_stderr, stderr_logger_stream)

        logger.info("Command started", scope="core")

        validate_requirements(ctx, opts, requirements)

        init_result = initialize_container_resources(
            container=container,
            requirements=requirements,
            logger=logger,
            run_id=run_id,
        )
        if init_result is not None:
            exit_result = init_result
        else:
            topology_step_result = run_topology_bootstrap(
                ctx=ctx,
                command_name=command_name,
                opts=opts,
                requirements=requirements,
                container=container,
                report_sink=NullReportSink(),
                logger=logger,
                run_id=run_id,
            )
            ctx = attach_topology_runtime(
                ctx=ctx,
                runtime_binding=topology_step_result.runtime_binding,
            )
            if topology_step_result.command_result is not None:
                exit_result = topology_step_result.command_result
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
        logger.error(
            "Settings error",
            scope="config",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
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
        logger.error(
            "DSL load error",
            scope="dsl",
            diag_code=exc.code,
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
        typer.echo(f"ERROR: {exc.code}: {exc}", err=True)
        result = DomainCommandResult()
        result.add_diagnostics([diag], ctx.catalog)
        exit_result = result
    except RuntimeErrorWithCode as exc:
        logger.error(
            "Runtime validation error",
            scope="config",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
        typer.echo(f"ERROR: {exc}", err=True)
        exit_result = build_runtime_error_result(
            catalog=ctx.catalog,
            command_name=command_name,
            message=str(exc),
            details={
                "runtime_exit_code": exc.exit_code,
                "runtime_error": "RuntimeErrorWithCode",
            },
        )
    except Exception as exc:
        logger.error(
            "Command failed",
            scope="core",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
        typer.echo("ERROR: command failed (see logs)", err=True)
        exit_result = build_runtime_error_result(
            catalog=ctx.catalog,
            command_name=command_name,
            message=str(exc),
            details={"runtime_error": exc.__class__.__name__},
        )
    finally:
        try:
            sys.stdout = original_stdout
            sys.stderr = original_stderr
            shutdown_result = shutdown_container_resources(
                container=container,
                logger=logger,
                run_id=run_id,
                emit_user_error=exit_result is None,
            )
            if exit_result is None and shutdown_result is not None:
                exit_result = shutdown_result
            _ = get_duration_ms(start_monotonic, time.monotonic())
            logger.info("Log written", scope="log", log_file_path=log_file_path)
            _publish_latest_artifact_pointers(
                container=container,
                logger=logger,
                run_id=run_id,
                log_file_path=log_file_path,
                report_path=None,
                plan_path=_resolve_runtime_plan_path(ctx=ctx, opts=opts),
            )
            if observability_session is not None:
                active_component = observability_session.component
            else:
                active_component = fallback_component
            _record_run_ledger_without_report(
                container=container,
                enabled=app_config.observability.ledger.enabled,
                component=active_component,
                logger=logger,
                run_id=run_id,
                pipeline_run_id=pipeline_run_id,
                started_at=started_at,
                log_file_path=log_file_path,
                plan_path=_resolve_runtime_plan_path(ctx=ctx, opts=opts),
                final_result=exit_result,
                exit_code_from_result=exit_code_from_result,
            )
        finally:
            close_observability_runtime(container)
            clear_observability_context()

        if exit_result is not None:
            raise typer.Exit(code=exit_code_from_result(exit_result))


def bind_context_with_container(
    ctx: UnboundCommandContext, *, container: AppContainer
) -> BoundCommandContext:
    """
    Назначение:
        Привязать command-context к инициализированному DI container.
    """
    return CommandContext(
        logger=ctx.logger,
        run_id=ctx.run_id,
        pipeline_run_id=ctx.pipeline_run_id,
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
    logger: Any,
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
        logger.error(
            "Container cache init failed",
            scope="cache",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
        typer.echo(
            "ERROR: failed to initialize cache resources (see logs/report)", err=True
        )
        return result_with(SystemErrorCode.CACHE_ERROR)
    except VaultDomainError as exc:
        logger.error(
            "Vault startup error",
            scope="vault",
            diag_code=exc.code,
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
        typer.echo(f"ERROR: {exc.code}: {exc}", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    except Exception as exc:
        logger.error(
            "Container resource init failed",
            scope="core",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
        typer.echo(
            "ERROR: failed to initialize runtime resources (see logs/report)", err=True
        )
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    return None


def shutdown_container_resources(
    *,
    container: AppContainer | None,
    logger: Any,
    run_id: str,
    emit_user_error: bool,
) -> RuntimeExecutionResult:
    """
    Назначение:
        Graceful shutdown DI ресурсов с runtime->result mapping.
    """
    if container is None:
        return None
    failures: list[tuple[str, Exception]] = []
    for subcontainer_name in _RESOURCE_SHUTDOWN_CONTAINERS:
        subcontainer = getattr(container, subcontainer_name)
        try:
            subcontainer.shutdown_resources()
        except Exception as exc:
            failures.append((subcontainer_name, exc))
            logger.error(
                "Container shutdown failed",
                scope="core",
                subcontainer=subcontainer_name,
                error=str(exc),
                error_type=exc.__class__.__name__,
            )

    if failures:
        logger.error(
            "Container shutdown completed with errors",
            scope="core",
            failed_subcontainers=[name for name, _ in failures],
        )
        if emit_user_error:
            typer.echo("ERROR: runtime teardown failed (see logs/report)", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    return None


def close_observability_runtime(container: AppContainer | None) -> None:
    """Закрыть observability runtime последним, после finalize/ledger/pointers."""
    if container is None:
        return
    try:
        container.observability.logging_runtime.shutdown()
    except Exception:
        # Последняя линия shutdown: runtime уже уходит, вторичную ошибку логировать некуда.
        return


def finalize_report_artifacts(
    *,
    report_sink,
    report_assembler: ReportAssembler,
    start_monotonic: float,
    paths,
    log_file_path: str | None,
    command_name: str,
    run_id: str,
    logger: Any,
    layout: ObservabilityLayout | None,
    component: ServiceComponent | None,
    emit_user_error: bool,
) -> RuntimeExecutionResult:
    """
    Назначение:
        Финализировать report envelope и записать JSON artifact.
    """
    try:
        duration_ms = get_duration_ms(start_monotonic, time.monotonic())
        report_sink.emit(
            SetContextEvent(
                name=ReportContextKey.RUNTIME,
                value={
                    "log_file": log_file_path,
                    "cache_dir": paths.cache_dir,
                    "report_dir": paths.report_dir,
                    "plans_dir": paths.plans_dir,
                },
            )
        )
        report_sink.emit(FinishEvent(duration_ms=duration_ms))
        envelope = report_assembler.assemble()
        if layout is None or component is None:
            raise RuntimeError("observability layout is not initialized")
        report_timestamp = _resolve_report_artifact_timestamp(envelope)
        report_path = JsonReportRenderer().render_with_layout(
            envelope=envelope,
            layout=layout,
            component=component,
            now=report_timestamp,
        )
        logger.info("Report written", scope="report", report_path=report_path)
    except Exception as exc:
        logger.error(
            "Report finalization failed",
            scope="report",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )
        if emit_user_error:
            typer.echo("ERROR: failed to finalize report (see logs)", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    return None


def _record_run_ledger_for_report(
    *,
    container: AppContainer | None,
    enabled: bool,
    component: ServiceComponent,
    layout: ObservabilityLayout,
    report_assembler: ReportAssembler,
    logger: Any,
    run_id: str,
    pipeline_run_id: str,
    started_at: str,
    log_file_path: str | None,
    plan_path: str | None,
    final_result: RuntimeExecutionResult,
    exit_code_from_result: Callable[[Any], int],
) -> None:
    """Собрать ledger-запись из финального отчёта и записать её best-effort."""
    try:
        envelope = report_assembler.assemble()
        report_path = None
        if envelope.meta.finished_at is not None:
            report_path = str(
                layout.report_file(
                    component,
                    now=_resolve_report_artifact_timestamp(envelope),
                )
            )
            if not Path(report_path).exists():
                report_path = None

        record = build_run_ledger_record(
            run_id=run_id,
            pipeline_run_id=pipeline_run_id,
            component=component,
            started_at=envelope.meta.started_at or started_at,
            finished_at=envelope.meta.finished_at,
            status=_resolve_ledger_status(
                final_result=final_result,
                fallback_status=envelope.status,
                exit_code_from_result=exit_code_from_result,
            ),
            log_path=_existing_path_or_none(log_file_path),
            report_path=report_path,
            plan_path=_existing_path_or_none(plan_path),
            row_counters=RunLedgerRowCounters(
                rows_total=envelope.summary.rows_total,
                rows_passed=envelope.summary.rows_passed,
                rows_blocked=envelope.summary.rows_blocked,
                rows_skipped=envelope.summary.rows_skipped,
                rows_with_warnings=envelope.summary.rows_with_warnings,
                errors_total=envelope.summary.errors_total,
                warnings_total=envelope.summary.warnings_total,
            ),
        )
        _persist_run_ledger_record(
            container=container,
            enabled=enabled,
            component=component,
            logger=logger,
            run_id=run_id,
            record=record,
        )
    except Exception as exc:
        logger.warning(
            "Ledger record assembly failed",
            scope="observability",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )


def _record_run_ledger_without_report(
    *,
    container: AppContainer | None,
    enabled: bool,
    component: ServiceComponent,
    logger: Any,
    run_id: str,
    pipeline_run_id: str,
    started_at: str,
    log_file_path: str | None,
    plan_path: str | None,
    final_result: RuntimeExecutionResult,
    exit_code_from_result: Callable[[Any], int],
) -> None:
    """Записать ledger для команд без report-артефакта."""
    try:
        finished_at = get_now_iso()
        record = build_run_ledger_record(
            run_id=run_id,
            pipeline_run_id=pipeline_run_id,
            component=component,
            started_at=started_at,
            finished_at=finished_at,
            status=_resolve_ledger_status(
                final_result=final_result,
                fallback_status="SUCCESS",
                exit_code_from_result=exit_code_from_result,
            ),
            log_path=_existing_path_or_none(log_file_path),
            report_path=None,
            plan_path=_existing_path_or_none(plan_path),
        )
        _persist_run_ledger_record(
            container=container,
            enabled=enabled,
            component=component,
            logger=logger,
            run_id=run_id,
            record=record,
        )
    except Exception as exc:
        logger.warning(
            "Ledger record assembly failed",
            scope="observability",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )


def _persist_run_ledger_record(
    *,
    container: AppContainer | None,
    enabled: bool,
    component: ServiceComponent,
    logger: Any,
    run_id: str,
    record,
) -> None:
    """Сделать best-effort append в run ledger без влияния на exit code."""
    if not enabled or container is None:
        return
    try:
        backend = container.observability.ledger_backend()
        backend.append(component=component, record=record)
    except Exception as exc:
        logger.warning(
            "Ledger append failed",
            scope="observability",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )


def _publish_latest_artifact_pointers_for_report(
    *,
    container: AppContainer | None,
    component: ServiceComponent | None,
    layout: ObservabilityLayout | None,
    report_assembler: ReportAssembler,
    logger: Any,
    run_id: str,
    log_file_path: str | None,
    plan_path: str | None,
) -> None:
    """Опубликовать stable pointers для log/report/plan у report-aware команд."""
    if component is None or layout is None:
        return
    try:
        envelope = report_assembler.assemble()
        report_path = None
        if envelope.meta.finished_at is not None:
            candidate = layout.report_file(
                component,
                now=_resolve_report_artifact_timestamp(envelope),
            )
            if candidate.exists() and candidate.is_file():
                report_path = str(candidate)
        _publish_latest_artifact_pointers(
            container=container,
            logger=logger,
            run_id=run_id,
            log_file_path=log_file_path,
            report_path=report_path,
            plan_path=plan_path,
        )
    except Exception as exc:
        logger.warning(
            "Latest pointer update failed",
            scope="observability",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )


def _publish_latest_artifact_pointers(
    *,
    container: AppContainer | None,
    logger: Any,
    run_id: str,
    log_file_path: str | None,
    report_path: str | None,
    plan_path: str | None,
) -> None:
    """Best-effort обновить `current.log` и `latest.json` pointers."""
    if container is None:
        return
    try:
        publisher = container.observability.pointer_publisher()
        publisher.publish(
            artifact_kind=ObservabilityArtifactKind.LOG,
            artifact_path=log_file_path,
        )
        publisher.publish(
            artifact_kind=ObservabilityArtifactKind.REPORT,
            artifact_path=report_path,
        )
        publisher.publish(
            artifact_kind=ObservabilityArtifactKind.PLAN,
            artifact_path=plan_path,
        )
    except Exception as exc:
        logger.warning(
            "Latest pointer update failed",
            scope="observability",
            error=str(exc),
            error_type=exc.__class__.__name__,
        )


def _resolve_report_artifact_timestamp(envelope) -> datetime:
    """Преобразовать `meta.finished_at` в datetime для детерминированного report path."""
    if envelope.meta.finished_at is None:
        raise RuntimeError("report meta.finished_at is missing")
    return datetime.fromisoformat(envelope.meta.finished_at)


def _resolve_runtime_plan_path(*, ctx: CommandContext[Any], opts: Any) -> str | None:
    """Извлечь путь плана из runtime context или CLI opts без знания handler-деталей."""
    extra = ctx.extra or {}
    plan_path = extra.get("plan_path")
    if isinstance(plan_path, str) and plan_path.strip():
        return plan_path
    opt_value = get_opt(opts, ("plan_path",))
    if isinstance(opt_value, str) and opt_value.strip():
        return opt_value
    return None


def _resolve_ledger_status(
    *,
    final_result: RuntimeExecutionResult,
    fallback_status: str,
    exit_code_from_result: Callable[[Any], int],
) -> str:
    """Нормализовать статус ledger к итоговому exit code выполнения."""
    if final_result is None:
        return fallback_status
    return "SUCCESS" if exit_code_from_result(final_result) == 0 else "FAILED"


def _existing_path_or_none(path_value: str | None) -> str | None:
    """Вернуть путь только если файл уже существует на диске."""
    if not path_value:
        return None
    return path_value if Path(path_value).exists() else None


def validate_requirements(
    ctx: CommandContext[Any], opts: Any, requirements: Requirements
) -> None:
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
        raise RuntimeErrorWithCode(
            "Dataset is required for source resolution", exit_code=2
        )
    try:
        source_spec = load_source_spec_for_dataset(dataset)
    except DslLoadError as exc:
        raise RuntimeErrorWithCode(
            f"Source spec is not configured for dataset '{dataset}': {exc.code}: {exc}",
            exit_code=2,
        ) from exc
    except Exception as exc:
        raise RuntimeErrorWithCode(
            f"Source spec is not configured for dataset '{dataset}': {exc}", exit_code=2
        ) from exc
    try:
        location = resolve_source_location(source_spec)
    except DslLoadError as exc:
        raise RuntimeErrorWithCode(
            f"Source location is not configured for dataset '{dataset}': {exc.code}: {exc}",
            exit_code=2,
        ) from exc
    except ValueError as exc:
        raise RuntimeErrorWithCode(
            f"Source location is not configured for dataset '{dataset}': {exc}",
            exit_code=2,
        ) from exc
    if source_spec.source.type == "file":
        path = Path(location)
        if not path.exists() or not path.is_file():
            raise RuntimeErrorWithCode(
                f"Source file not found: {location}", exit_code=2
            )


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
        raise RuntimeErrorWithCode(
            f"Missing API settings: {', '.join(missing)}", exit_code=2
        )


def require_cache(app_config: AppConfig) -> None:
    cache_dir = Path(to_operational_paths(app_config).cache_dir)
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeErrorWithCode(
            f"Cache dir not доступен: {exc}", exit_code=2
        ) from exc


def require_secrets(vault_mode: str | None) -> None:
    normalized = (vault_mode or "auto").strip().lower()
    if normalized == "off":
        raise RuntimeErrorWithCode(
            "vault-mode=off is incompatible with command requirements", exit_code=2
        )


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


def _console_log_mirror_enabled(ctx: CommandContext[Any]) -> bool:
    extra = ctx.extra or {}
    quiet = bool(extra.get("quiet"))
    requested = bool(extra.get("console_log_mirror"))
    return requested and not quiet


def _run_topology_bootstrap_if_needed(
    *,
    ctx: UnboundCommandContext,
    command_name: str,
    opts: Any,
    requirements: Requirements,
    container: AppContainer,
    report_sink,
    logger: Any,
    run_id: str,
):
    if command_name not in TOPOLOGY_PIPELINE_COMMANDS:
        return TopologyBootstrapStepResult.inactive(requirements)
    dataset_name = resolve_dataset_opt(opts, ctx.app_config)
    if dataset_name is None:
        return TopologyBootstrapStepResult.inactive(requirements)
    step = TopologyBootstrapStep()
    return step.run(
        ctx=ctx,
        command_name=command_name,
        dataset_name=dataset_name,
        requirements=requirements,
        container=container,
        report_sink=report_sink,
        logger=logger,
        run_id=run_id,
    )


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
