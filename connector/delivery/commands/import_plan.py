from __future__ import annotations

import logging
import sqlite3

import typer

from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.datasets.registry import resolve_dataset_name
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.datasets.cache_registry import list_cache_specs
from connector.infra.cache.db import openCacheDb, getCacheDbPath
from connector.infra.logging.setup import logEvent
from connector.usecases.import_plan_service import ImportPlanService


def run(
    *,
    ctx: typer.Context,
    csv_path: str | None,
    csv_has_header: bool | None,
    include_deleted: bool | None,
    report_items_limit: int | None,
    dataset: str | None,
    vault_file: str | None,
    logger,
) -> CommandResult:
    """
    Назначение:
        Запустить сценарий import-plan, изолируя wiring от main.py.
    """
    settings = ctx.obj["settings"]
    run_id = ctx.obj["runId"]
    cache_db_path = getCacheDbPath(settings.cache_dir)

    dataset_name = resolve_dataset_name(dataset, settings.dataset_name)

    try:
        conn = openCacheDb(cache_db_path)
    except sqlite3.Error as exc:
        logEvent(logger, logging.ERROR, run_id, "cache", f"Failed to open cache DB: {exc}")
        typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
        return _result_with(SystemErrorCode.CACHE_ERROR)

    include_deleted_value = include_deleted if include_deleted is not None else settings.include_deleted
    report_items_limit_value = (
        report_items_limit if report_items_limit is not None else settings.report_items_limit
    )
    csv_has_header_value = csv_has_header if csv_has_header is not None else settings.csv_has_header

    try:
        engine = SqliteEngine(conn)
        cache_specs = list_cache_specs()
        ensure_cache_ready(engine, cache_specs)

        service = ImportPlanService()
        return service.run(
            conn=conn,
            csv_path=csv_path or "",
            csv_has_header=csv_has_header_value,
            include_deleted=include_deleted_value,
            settings=settings,
            dataset=dataset_name,
            logger=logger,
            run_id=run_id,
            report_items_limit=report_items_limit_value,
            report_dir=settings.report_dir,
            vault_file=vault_file,
        )
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        return _result_with(SystemErrorCode.INTERNAL_ERROR)
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "plan", f"Import plan failed: {exc}")
        typer.echo("ERROR: import plan failed (see logs)", err=True)
        return _result_with(SystemErrorCode.INTERNAL_ERROR)
    finally:
        conn.close()


def _result_with(code: SystemErrorCode) -> CommandResult:
    result = CommandResult()
    result.add_code(code)
    return result


__all__ = ["run"]
