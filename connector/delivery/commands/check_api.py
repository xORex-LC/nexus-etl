from __future__ import annotations

from dataclasses import dataclass

import typer

from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.commands.common import result_with
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.reporting.contracts import ReportContextKey
from connector.domain.reporting.events import SetContextEvent


@dataclass(frozen=True)
class Options:
    api_transport: object | None = None


def _runtime_context(build_result) -> dict[str, str]:
    return {
        "target_runtime_mode": build_result.effective_mode,
        "target_runtime_requested_mode": build_result.requested_mode,
    }


def handler(ctx: BoundCommandContext, opts: Options, report_sink) -> CommandResult:
    app_config = ctx.app_config
    if app_config is None:
        raise ValueError("App settings are not initialized")
    build_result = ctx.container.target.runtime()
    runtime = build_result.runtime

    report_sink.emit(
        SetContextEvent(
            name=ReportContextKey.TARGET_RUNTIME, value=_runtime_context(build_result)
        )
    )
    result = runtime.check()
    target_meta = runtime.meta()

    if result.ok:
        ctx.logger.info(
            "API check succeeded",
            scope="api",
            endpoint=target_meta.endpoint,
            latency_ms=result.latency_ms,
        )
        report_sink.emit(
            SetContextEvent(
                name=ReportContextKey.APPLY_TARGET,
                value={
                    "target_type": target_meta.target_type,
                    "transport": target_meta.transport,
                    "target_runtime_mode": build_result.effective_mode,
                },
            )
        )
        return result_with(SystemErrorCode.OK)

    ctx.logger.error(
        "API check failed",
        scope="api",
        error=result.error_message,
        error_code=result.error_code.name if result.error_code else None,
    )
    typer.echo("ERROR: API check failed (see logs/report)", err=True)
    return result_with(result.error_code or SystemErrorCode.INFRA_UNAVAILABLE)


__all__ = ["handler", "Options"]
