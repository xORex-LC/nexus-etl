"""
Назначение:
    Thin facade для CLI runtime orchestration и runtime result adapters.

Граница ответственности:
    - Делегирует orchestration в `runtime.orchestrator`.
    - Делегирует mapping результата в `runtime.result_mapper`.
    - Делегирует boundary result adaptation в `runtime.result_adapter`.

Обратная совместимость:
    Приватные helper-имена сохранены как facade wrappers, чтобы поддержать
    текущие тесты без legacy compatibility-веток runtime результата.
"""

from __future__ import annotations

import logging
from typing import Any

from connector.delivery.cli.containers import AppContainer, _init_container_for_requirements
from connector.delivery.cli.context import BoundCommandContext, CommandContext, UnboundCommandContext
from connector.delivery.cli.requirements import Requirements
from .contracts import (
    CommandHandler,
    RuntimeErrorWithCode,
    RuntimeExecutionResult,
)
from connector.delivery.cli.runtime import orchestrator as runtime_orchestrator
from .result_adapter import exit_code_from_result, result_with
from .result_mapper import (
    apply_runtime_result_to_report,
    build_runtime_error_result,
    stage_for_command,
)
from connector.domain.reporting.context import IReportContext


ReportHandler = CommandHandler


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
        Thin facade над runtime_orchestrator.run_with_report().
    """
    runtime_orchestrator.run_with_report(
        ctx=ctx,
        command_name=command_name,
        opts=opts,
        handler=handler,
        requirements=requirements,
        create_container=AppContainer,
        initialize_container_resources=_initialize_container_resources,
        shutdown_container_resources=_shutdown_container_resources,
        finalize_report_artifacts=_finalize_report_artifacts,
        apply_result_to_report=_apply_cli_result_to_report,
        exit_code_from_result=_exit_code_from_result,
        run_topology_bootstrap=_run_topology_bootstrap_if_needed,
    )


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
        Thin facade над runtime_orchestrator.run_without_report().
    """
    runtime_orchestrator.run_without_report(
        ctx=ctx,
        command_name=command_name,
        opts=opts,
        handler=handler,
        requirements=requirements,
        create_container=AppContainer,
        initialize_container_resources=_initialize_container_resources,
        shutdown_container_resources=_shutdown_container_resources,
        exit_code_from_result=_exit_code_from_result,
        run_topology_bootstrap=_run_topology_bootstrap_if_needed,
    )


def _run_topology_bootstrap_if_needed(**kwargs):
    """
    Назначение:
        Compatibility facade для topology bootstrap step (инжектируемый seam).

    Граница:
        Делает topology bootstrap таким же подменяемым в тестах runtime-обвязки,
        как и остальные инфраструктурные ресурсы (init/shutdown/finalize).
    """
    return runtime_orchestrator._run_topology_bootstrap_if_needed(**kwargs)


def _bind_context_with_container(ctx: UnboundCommandContext, *, container: AppContainer) -> BoundCommandContext:
    """
    Назначение:
        Compatibility facade для lifecycle tests.
    """
    return runtime_orchestrator.bind_context_with_container(ctx, container=container)


def _initialize_container_resources(
    *,
    container: AppContainer,
    requirements: Requirements,
    logger: logging.Logger,
    run_id: str,
) -> RuntimeExecutionResult:
    """
    Назначение:
        Compatibility facade для runtime init mapping.
    """
    return runtime_orchestrator.initialize_container_resources(
        container=container,
        requirements=requirements,
        logger=logger,
        run_id=run_id,
        init_container_for_requirements=_init_container_for_requirements,
    )


def _shutdown_container_resources(
    *,
    container: AppContainer | None,
    logger: logging.Logger,
    run_id: str,
    emit_user_error: bool,
) -> RuntimeExecutionResult:
    """
    Назначение:
        Compatibility facade для runtime shutdown mapping.
    """
    return runtime_orchestrator.shutdown_container_resources(
        container=container,
        logger=logger,
        run_id=run_id,
        emit_user_error=emit_user_error,
    )


def _finalize_report_artifacts(
    *,
    report_sink,
    report_assembler,
    start_monotonic: float,
    paths,
    log_file_path: str | None,
    command_name: str,
    run_id: str,
    logger,
    layout=None,
    component=None,
    emit_user_error: bool,
) -> RuntimeExecutionResult:
    """
    Назначение:
        Compatibility facade для report finalization.
    """
    return runtime_orchestrator.finalize_report_artifacts(
        report_sink=report_sink,
        report_assembler=report_assembler,
        start_monotonic=start_monotonic,
        paths=paths,
        log_file_path=log_file_path,
        command_name=command_name,
        run_id=run_id,
        logger=logger,
        layout=layout,
        component=component,
        emit_user_error=emit_user_error,
    )


def _validate_requirements(ctx: CommandContext[Any], opts: Any, requirements: Requirements) -> None:
    """
    Назначение:
        Compatibility facade для runtime requirements gate.
    """
    runtime_orchestrator.validate_requirements(ctx, opts, requirements)


def _require_source(dataset: str | None) -> None:
    runtime_orchestrator.require_source(dataset)


def _require_api(app_config) -> None:
    runtime_orchestrator.require_api(app_config)


def _require_cache(app_config) -> None:
    runtime_orchestrator.require_cache(app_config)


def _require_secrets(vault_mode: str | None) -> None:
    runtime_orchestrator.require_secrets(vault_mode)


def _require_dataset(dataset: str | None) -> None:
    runtime_orchestrator.require_dataset(dataset)


def _call_handler(
    handler: ReportHandler,
    ctx: BoundCommandContext,
    opts: Any,
    report_sink,
) -> RuntimeExecutionResult:
    """Purpose:
        Compatibility helper для явного 3-arg handler contract.

    Contract:
        Reflection dispatch удален; runtime всегда вызывает handler(ctx, opts, report_sink).
    """
    return handler(ctx, opts, report_sink)


def _apply_cli_result_to_report(
    report_sink,
    report_context: IReportContext,
    result: Any,
    *,
    command_name: str,
    source: str,
    secondary: bool,
) -> None:
    """Purpose:
        Compatibility facade: runtime result -> report mapping.
    """
    apply_runtime_result_to_report(
        report_sink,
        report_context,
        result,
        command_name=command_name,
        source=source,
        secondary=secondary,
    )


def _runtime_error_result(
    *,
    catalog,
    command_name: str,
    message: str,
    details: dict[str, Any] | None = None,
):
    return build_runtime_error_result(
        catalog=catalog,
        command_name=command_name,
        message=message,
        details=details,
    )


def _result_with(code):
    return result_with(code)


def _exit_code_from_result(result: Any) -> int:
    return exit_code_from_result(result)


def _resolve_dataset_opt(opts: Any, app_config):
    return runtime_orchestrator.resolve_dataset_opt(opts, app_config)


def _get_opt(opts: Any, names: tuple[str, ...]) -> Any:
    return runtime_orchestrator.get_opt(opts, names)


def _config_sources(ctx: CommandContext[Any]) -> list[str]:
    return runtime_orchestrator.config_sources(ctx)


def _require_app_settings(ctx: CommandContext[Any]):
    return runtime_orchestrator.require_app_settings(ctx)


def _echo_command_diagnostics(prefix: str, diagnostics: list[Any]) -> None:
    runtime_orchestrator.echo_command_diagnostics(prefix, diagnostics)


def _stage_for_command(command_name: str):
    return stage_for_command(command_name)


__all__ = [
    "AppContainer",
    "ReportHandler",
    "RuntimeErrorWithCode",
    "run_with_report",
    "run_without_report",
]
