from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.commands.common import result_with
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.delivery.cli.bootstrap import build_api_client, build_target_runtime
from connector.infra.logging.setup import logEvent


@dataclass(frozen=True)
class Options:
    api_transport: object | None = None


def _extract_transport(client: object) -> object | None:
    http_client = getattr(client, "client", None)
    return getattr(http_client, "_transport", None)


def _close_http_client(client: object) -> None:
    http_client = getattr(client, "client", None)
    close = getattr(http_client, "close", None)
    if callable(close):
        close()


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    app_settings = ctx.app_settings
    if app_settings is None:
        raise ValueError("App settings are not initialized")
    run_id = ctx.run_id

    legacy_client = build_api_client(app_settings.api, transport=opts.api_transport)
    runtime_transport = opts.api_transport or _extract_transport(legacy_client)

    if runtime_transport is None and hasattr(legacy_client, "getJson"):
        try:
            start = time.monotonic()
            legacy_client.getJson("/ankey/managed/user", {"page": 1, "rows": 1, "_queryFilter": "true"})  # noqa: N802
            latency_ms = int((time.monotonic() - start) * 1000)
            logEvent(
                ctx.logger, logging.INFO, run_id, "api",
                f"api ok base_url=https://{app_settings.api.host}:{app_settings.api.port} latency_ms={latency_ms}",
            )
            report.set_context("apply_target", {"target_type": "http"})
            return result_with(SystemErrorCode.OK)
        except Exception as exc:  # pragma: no cover - compatibility fallback
            logEvent(ctx.logger, logging.ERROR, run_id, "api", f"API check failed: {exc}")
            typer.echo("ERROR: API check failed (see logs/report)", err=True)
            return result_with(SystemErrorCode.INFRA_UNAVAILABLE)
    _close_http_client(legacy_client)

    runtime = build_target_runtime(
        app_settings.api,
        transport=runtime_transport,
        include_reader=False,
    )
    result = runtime.check()
    target_meta = runtime.meta()

    if result.ok:
        logEvent(
            ctx.logger, logging.INFO, run_id, "api",
            f"api ok base_url={target_meta.base_url} latency_ms={result.latency_ms}",
        )
        report.set_context("apply_target", {"target_type": target_meta.transport})
        return result_with(SystemErrorCode.OK)

    logEvent(
        ctx.logger, logging.ERROR, run_id, "api",
        f"API check failed: {result.error_message}",
    )
    typer.echo("ERROR: API check failed (see logs/report)", err=True)
    return result_with(result.error_code or SystemErrorCode.INFRA_UNAVAILABLE)


__all__ = ["handler", "Options"]
