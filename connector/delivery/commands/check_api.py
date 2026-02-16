from __future__ import annotations

import logging
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.commands.common import result_with
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.delivery.cli.bootstrap import build_target_runtime_with_info
from connector.infra.logging.setup import logEvent


@dataclass(frozen=True)
class Options:
    api_transport: object | None = None


def _runtime_context(build_result) -> dict[str, str]:
    return {
        "target_runtime_mode": build_result.effective_mode,
        "target_runtime_requested_mode": build_result.requested_mode,
    }


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    app_settings = ctx.app_settings
    if app_settings is None:
        raise ValueError("App settings are not initialized")
    run_id = ctx.run_id

    build_result = build_target_runtime_with_info(
        app_settings.api,
        transport=opts.api_transport,
        include_reader=False,
    )
    runtime = build_result.runtime
    try:
        report.set_context("target_runtime", _runtime_context(build_result))
        result = runtime.check()
        target_meta = runtime.meta()

        if result.ok:
            logEvent(
                ctx.logger, logging.INFO, run_id, "api",
                f"api ok base_url={target_meta.base_url} latency_ms={result.latency_ms}",
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
    finally:
        runtime.close()


__all__ = ["handler", "Options"]
