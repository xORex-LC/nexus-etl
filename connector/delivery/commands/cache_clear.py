from __future__ import annotations

import logging
import sqlite3

import typer

from connector.delivery.bootstrap import build_diagnostics_catalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.datasets.cache_registry import list_cache_specs
from connector.infra.cache.db import openCacheDb, getCacheDbPath
from connector.infra.cache.repository import SqliteCacheRepository
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.logging.setup import logEvent
from connector.usecases.cache_clear_usecase import CacheClearUseCase
from connector.usecases.cache_command_service import CacheCommandService


def run(*, ctx: typer.Context, dataset: str | None, logger, report) -> CommandResult:
    settings = ctx.obj["settings"]
    run_id = ctx.obj["runId"]
    cache_db_path = getCacheDbPath(settings.cache_dir)

    build_diagnostics_catalog(dataset, strict=settings.diagnostics_strict)

    try:
        conn = openCacheDb(cache_db_path)
    except sqlite3.Error as exc:
        logEvent(logger, logging.ERROR, run_id, "cache", f"Failed to open cache DB: {exc}")
        typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
        return _result_with(SystemErrorCode.CACHE_ERROR)

    try:
        engine = SqliteEngine(conn)
        cache_specs = list_cache_specs()
        ensure_cache_ready(engine, cache_specs)

        cache_repo = SqliteCacheRepository(engine, cache_specs)
        if dataset is not None and dataset not in cache_repo.list_datasets():
            typer.echo(f"ERROR: Unsupported cache dataset: {dataset}", err=True)
            return _result_with(SystemErrorCode.CACHE_ERROR)
        cache_clear = CacheClearUseCase(cache_repo)
        service = CacheCommandService(cache_repo, cache_clear=cache_clear)
        result = service.clear(logger, report, run_id, dataset=dataset)
        exit_code = result.exit_code()
        if exit_code != 0:
            typer.echo("ERROR: cache clear failed (see logs/report)", err=True)
            return result
        return result
    finally:
        conn.close()


def _result_with(code: SystemErrorCode) -> CommandResult:
    result = CommandResult()
    result.add_code(code)
    return result


__all__ = ["run"]
