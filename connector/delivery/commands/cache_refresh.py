from __future__ import annotations

import logging
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.commands.common import ensure_supported_cache_dataset, result_with
from connector.delivery.cli.bootstrap import (
    build_cache,
    build_api_reader,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.datasets.cache_registry import list_cache_sync_adapters
from connector.datasets.registry import build_identity_index_plan
from connector.infra.http.ankey_client import AnkeyApiClient
from connector.infra.logging.setup import logEvent
from connector.usecases.cache_command_service import CacheCommandService
from connector.usecases.cache_refresh_service import CacheRefreshUseCase


@dataclass(frozen=True)
class Options:
    page_size: int | None = None
    max_pages: int | None = None
    timeout_seconds: float | None = None
    retries: int | None = None
    retry_backoff_seconds: float | None = None
    api_transport: object | None = None
    include_deleted: bool | None = None
    report_items_limit: int | None = None
    dataset: str | None = None


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    settings = ctx.settings
    run_id = ctx.run_id

    conn = None
    try:
        conn, _engine, _gateway, cache_roles, _cache_specs = build_cache(settings)
        unsupported_result = ensure_supported_cache_dataset(cache_roles.cache_admin, opts.dataset)
        if unsupported_result is not None:
            return unsupported_result

        base_url = f"https://{settings.host}:{settings.port}"
        client = _build_api_client(settings, opts.api_transport)
        client.resetRetryAttempts()
        reader = build_api_reader(client)

        adapters = list_cache_sync_adapters()
        identity_keys, identity_id_fields = build_identity_index_plan()
        cache_refresh = CacheRefreshUseCase(
            reader,
            cache_roles.cache_refresh,
            adapters,
            identity_keys=identity_keys,
            identity_id_fields=identity_id_fields,
        )
        service = CacheCommandService(cache_roles.cache_admin, cache_refresh)

        return service.refresh(
            page_size=opts.page_size or settings.page_size,
            max_pages=opts.max_pages or settings.max_pages,
            logger=ctx.logger,
            report=report,
            run_id=run_id,
            include_deleted=opts.include_deleted if opts.include_deleted is not None else settings.include_deleted,
            report_items_limit=opts.report_items_limit or settings.report_items_limit,
            api_base_url=base_url,
            retries=opts.retries or settings.retries,
            retry_backoff_seconds=opts.retry_backoff_seconds or settings.retry_backoff_seconds,
            dataset=opts.dataset,
            catalog=ctx.catalog,
        )
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    except Exception as exc:
        logEvent(ctx.logger, logging.ERROR, run_id, "cache", f"Cache refresh failed: {exc}")
        typer.echo("ERROR: cache refresh failed (see logs/report)", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    finally:
        if conn is not None:
            conn.close()

def _build_api_client(settings, transport=None) -> AnkeyApiClient:
    return AnkeyApiClient(
        baseUrl=f"https://{settings.host}:{settings.port}",
        username=settings.api_username or "",
        password=settings.api_password or "",
        timeoutSeconds=settings.timeout_seconds,
        tlsSkipVerify=settings.tls_skip_verify,
        caFile=settings.ca_file,
        retries=settings.retries,
        retryBackoffSeconds=settings.retry_backoff_seconds,
        transport=transport,
    )


__all__ = ["handler", "Options"]
