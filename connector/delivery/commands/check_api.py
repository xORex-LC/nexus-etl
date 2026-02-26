from __future__ import annotations

import logging
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.commands.common import result_with
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.logging.setup import logEvent


@dataclass(frozen=True)
class Options:
    api_transport: object | None = None


def _runtime_context(build_result) -> dict[str, str]:
    return {
        "target_runtime_mode": build_result.effective_mode,
        "target_runtime_requested_mode": build_result.requested_mode,
    }


def handler(ctx: BoundCommandContext, opts: Options, report) -> CommandResult:
    app_config = ctx.app_config
    if app_config is None:
        raise ValueError("App settings are not initialized")
    run_id = ctx.run_id

    build_result = ctx.container.target.runtime()
    runtime = build_result.runtime

    report.set_context("target_runtime", _runtime_context(build_result))
    result = runtime.check()
    target_meta = runtime.meta()

    if result.ok:
        logEvent(
            ctx.logger, logging.INFO, run_id, "api",
            f"api ok endpoint={target_meta.endpoint} latency_ms={result.latency_ms}",
        )
        report.set_context(
            "apply_target",
            {
                "target_type": target_meta.target_type,
                "transport": target_meta.transport,
                "target_runtime_mode": build_result.effective_mode,
            },
        )
        return result_with(SystemErrorCode.OK)

    logEvent(
        ctx.logger, logging.ERROR, run_id, "api",
        f"API check failed: {result.error_message}",
    )
    typer.echo("ERROR: API check failed (see logs/report)", err=True)
    return result_with(result.error_code or SystemErrorCode.INFRA_UNAVAILABLE)


__all__ = ["handler", "Options"]
