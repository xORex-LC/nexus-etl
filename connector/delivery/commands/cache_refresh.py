from __future__ import annotations

import logging
import sqlite3

import typer

from connector.delivery.bootstrap import build_diagnostics_catalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.datasets.cache_registry import list_cache_sync_adapters, list_cache_specs
from connector.datasets.registry import build_identity_index_plan
from connector.infra.cache.db import openCacheDb, getCacheDbPath
from connector.infra.cache.identity_repository import SqliteIdentityRepository
from connector.infra.cache.pending_links_repository import SqlitePendingLinksRepository
from connector.infra.cache.repository import SqliteCacheRepository
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.http.ankey_client import AnkeyApiClient
from connector.infra.logging.setup import logEvent
from connector.infra.target.ankey_gateway import AnkeyTargetPagedReader
from connector.usecases.cache_command_service import CacheCommandService
from connector.usecases.cache_refresh_service import CacheRefreshUseCase


def run(
    *,
    ctx: typer.Context,
    page_size: int | None,
    max_pages: int | None,
    timeout_seconds: float | None,
    retries: int | None,
    retry_backoff_seconds: float | None,
    api_transport=None,
    include_deleted: bool | None = None,
    report_items_limit: int | None = None,
    dataset: str | None = None,
    logger,
    report,
) -> CommandResult:
    settings = ctx.obj["settings"]
    run_id = ctx.obj["runId"]
    cache_db_path = getCacheDbPath(settings.cache_dir)

    catalog = build_diagnostics_catalog(dataset, strict=settings.diagnostics_strict)
    report.set_meta(items_limit=report_items_limit if report_items_limit is not None else settings.report_items_limit)

    try:
        requireApi(settings)
    except typer.Exit:
        logEvent(logger, logging.ERROR, run_id, "config", "Missing API settings")
        typer.echo("ERROR: missing API settings (see logs/report)", err=True)
        return _result_with(SystemErrorCode.INTERNAL_ERROR)

    try:
        conn = openCacheDb(cache_db_path)
    except sqlite3.Error as exc:
        logEvent(logger, logging.ERROR, run_id, "cache", f"Failed to open cache DB: {exc}")
        typer.echo("ERROR: failed to open cache DB (see logs)", err=True)
        return _result_with(SystemErrorCode.CACHE_ERROR)

    try:
        base_url = f"https://{settings.host}:{settings.port}"
        client = AnkeyApiClient(
            baseUrl=base_url,
            username=settings.api_username or "",
            password=settings.api_password or "",
            timeoutSeconds=timeout_seconds or settings.timeout_seconds,
            tlsSkipVerify=settings.tls_skip_verify,
            caFile=settings.ca_file,
            retries=retries or settings.retries,
            retryBackoffSeconds=retry_backoff_seconds or settings.retry_backoff_seconds,
            transport=api_transport,
        )
        client.resetRetryAttempts()

        engine = SqliteEngine(conn)
        cache_specs = list_cache_specs()
        ensure_cache_ready(engine, cache_specs)

        cache_repo = SqliteCacheRepository(engine, cache_specs)
        if dataset is not None and dataset not in cache_repo.list_datasets():
            typer.echo(f"ERROR: Unsupported cache dataset: {dataset}", err=True)
            return _result_with(SystemErrorCode.CACHE_ERROR)
        reader = AnkeyTargetPagedReader(client)
        adapters = list_cache_sync_adapters()
        identity_keys, identity_id_fields = build_identity_index_plan()
        identity_repo = SqliteIdentityRepository(engine)
        pending_repo = SqlitePendingLinksRepository(engine)
        cache_refresh = CacheRefreshUseCase(
            reader,
            cache_repo,
            adapters,
            identity_repo=identity_repo,
            identity_keys=identity_keys,
            identity_id_fields=identity_id_fields,
            pending_repo=pending_repo,
        )
        service = CacheCommandService(cache_repo, cache_refresh)

        return service.refresh(
            page_size=page_size or settings.page_size,
            max_pages=max_pages or settings.max_pages,
            logger=logger,
            report=report,
            run_id=run_id,
            include_deleted=include_deleted if include_deleted is not None else settings.include_deleted,
            report_items_limit=report_items_limit or settings.report_items_limit,
            api_base_url=base_url,
            retries=retries or settings.retries,
            retry_backoff_seconds=retry_backoff_seconds or settings.retry_backoff_seconds,
            dataset=dataset,
            catalog=catalog,
        )
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        return _result_with(SystemErrorCode.INTERNAL_ERROR)
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "cache", f"Cache refresh failed: {exc}")
        typer.echo("ERROR: cache refresh failed (see logs/report)", err=True)
        return _result_with(SystemErrorCode.INTERNAL_ERROR)
    finally:
        conn.close()


def requireApi(settings) -> None:
    if not settings.api_username or not settings.api_password or not settings.host or not settings.port:
        raise typer.Exit(code=2)


def _result_with(code: SystemErrorCode) -> CommandResult:
    result = CommandResult()
    result.add_code(code)
    return result


__all__ = ["run"]
