from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.cli.bootstrap import build_cache
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.logging.setup import logEvent
from connector.usecases.cache_command_service import CacheCommandService


@dataclass(frozen=True)
class Options:
    dataset: str | None = None


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    settings = ctx.settings
    run_id = ctx.run_id

    conn = None
    try:
        conn, _engine, cache_repo, _cache_specs = build_cache(settings)
        if opts.dataset is not None and opts.dataset not in cache_repo.list_datasets():
            typer.echo(f"ERROR: Unsupported cache dataset: {opts.dataset}", err=True)
            return _result_with(SystemErrorCode.CACHE_ERROR)
        service = CacheCommandService(cache_repo)
        result = service.status(ctx.logger, report, run_id, dataset=opts.dataset)
        exit_code = result.exit_code()
        status = result.summary or {}
        if exit_code != 0:
            typer.echo("ERROR: cache status failed (see logs/report)", err=True)
            return result
        if "by_dataset" in status:
            schema_version = status.get("schema_version")
            total = status.get("total")
            typer.echo(f"schema_version={schema_version} total={total}")
            for name, info in status["by_dataset"].items():
                typer.echo(f"{name}: count={info.get('count')} meta={info.get('meta')}")
        else:
            typer.echo(
                "schema_version={schema_version} dataset={dataset} counts={counts} meta={meta}".format(
                    **status
                )
            )
        return result
    except sqlite3.Error as exc:
        logEvent(ctx.logger, logging.ERROR, run_id, "cache", f"Failed to open cache DB: {exc}")
        typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
        return _result_with(SystemErrorCode.CACHE_ERROR)
    finally:
        if conn is not None:
            conn.close()


def _result_with(code: SystemErrorCode) -> CommandResult:
    result = CommandResult()
    result.add_code(code)
    return result


__all__ = ["handler", "Options"]
