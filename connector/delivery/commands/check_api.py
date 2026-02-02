from __future__ import annotations

import logging
import time

import typer

from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.http.ankey_client import AnkeyApiClient, ApiError
from connector.infra.logging.setup import logEvent


def run(*, ctx: typer.Context, api_transport=None, logger, report) -> CommandResult:
    settings = ctx.obj["settings"]
    run_id = ctx.obj["runId"]

    base_url = f"https://{settings.host}:{settings.port}"
    client = AnkeyApiClient(
        baseUrl=base_url,
        username=settings.api_username or "",
        password=settings.api_password or "",
        timeoutSeconds=settings.timeout_seconds,
        tlsSkipVerify=settings.tls_skip_verify,
        caFile=settings.ca_file,
        retries=settings.retries,
        retryBackoffSeconds=settings.retry_backoff_seconds,
        transport=api_transport,
    )
    try:
        start = time.monotonic()
        client.getJson("/ankey/managed/user", {"page": 1, "rows": 1, "_queryFilter": "true"})
        latency_ms = int((time.monotonic() - start) * 1000)
        logEvent(logger, logging.INFO, run_id, "api", f"api ok base_url={base_url} latency_ms={latency_ms}")
        report.set_context("apply_target", {"target_type": "http"})
        return _result_ok()
    except ApiError as exc:
        logEvent(logger, logging.ERROR, run_id, "api", f"API check failed: {exc}")
        typer.echo("ERROR: API check failed (see logs/report)", err=True)
        return _result_with(SystemErrorCode.INFRA_UNAVAILABLE)


def _result_with(code: SystemErrorCode) -> CommandResult:
    result = CommandResult()
    result.add_code(code)
    return result


def _result_ok() -> CommandResult:
    result = CommandResult()
    result.add_code(SystemErrorCode.OK)
    return result


__all__ = ["run"]
