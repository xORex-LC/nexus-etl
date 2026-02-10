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
from connector.usecases.cache_command_service import CacheCommandService


@dataclass(frozen=True)
class Options:
    dataset: str | None = None


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    settings = ctx.settings
    run_id = ctx.run_id

    gateway = None
    try:
        gateway, cache_roles, _cache_specs = build_cache(settings)
        unsupported_result = ensure_supported_cache_dataset(cache_roles.cache_admin, opts.dataset)
        if unsupported_result is not None:
            return unsupported_result
        service = CacheCommandService(cache_roles.cache_admin)
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
        return sqlite_cache_error_result(logger=ctx.logger, run_id=run_id, scope="cache-status", exc=exc)
    finally:
        if gateway is not None:
            gateway.close()


__all__ = ["handler", "Options"]
