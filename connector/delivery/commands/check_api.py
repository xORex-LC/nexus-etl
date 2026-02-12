from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.commands.common import result_with
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.delivery.cli.bootstrap import build_api_client
from connector.infra.http.ankey_client import ApiError
from connector.infra.logging.setup import logEvent


@dataclass(frozen=True)
class Options:
    api_transport: object | None = None


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    app_settings = ctx.app_settings
    if app_settings is None:
        raise ValueError("App settings are not initialized")
    run_id = ctx.run_id

    base_url = f"https://{app_settings.api.host}:{app_settings.api.port}"
    client = build_api_client(app_settings.api, transport=opts.api_transport)
    try:
        start = time.monotonic()
        client.getJson("/ankey/managed/user", {"page": 1, "rows": 1, "_queryFilter": "true"})
        latency_ms = int((time.monotonic() - start) * 1000)
        logEvent(ctx.logger, logging.INFO, run_id, "api", f"api ok base_url={base_url} latency_ms={latency_ms}")
        report.set_context("apply_target", {"target_type": "http"})
        return result_with(SystemErrorCode.OK)
    except ApiError as exc:
        logEvent(ctx.logger, logging.ERROR, run_id, "api", f"API check failed: {exc}")
        typer.echo("ERROR: API check failed (see logs/report)", err=True)
        return result_with(SystemErrorCode.INFRA_UNAVAILABLE)


__all__ = ["handler", "Options"]
