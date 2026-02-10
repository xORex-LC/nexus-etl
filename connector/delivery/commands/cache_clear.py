from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.cli.bootstrap import build_cache
from connector.delivery.commands.common import (
    ensure_supported_cache_dataset,
    sqlite_cache_error_result,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.usecases.cache_clear_usecase import CacheClearUseCase
from connector.usecases.cache_command_service import CacheCommandService


@dataclass(frozen=True)
class Options:
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
        cache_clear = CacheClearUseCase(cache_roles.cache_admin)
        service = CacheCommandService(cache_roles.cache_admin, cache_clear=cache_clear)
        result = service.clear(ctx.logger, report, run_id, dataset=opts.dataset)
        exit_code = result.exit_code()
        if exit_code != 0:
            typer.echo("ERROR: cache clear failed (see logs/report)", err=True)
            return result
        return result
    except sqlite3.Error as exc:
        return sqlite_cache_error_result(logger=ctx.logger, run_id=run_id, scope="cache-clear", exc=exc)
    finally:
        if conn is not None:
            conn.close()


__all__ = ["handler", "Options"]
