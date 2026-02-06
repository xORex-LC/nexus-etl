from __future__ import annotations

import logging
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.cli.bootstrap import build_cache, build_dataset_spec
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.logging.setup import logEvent
from connector.usecases.import_plan_service import ImportPlanService


@dataclass(frozen=True)
class Options:
    csv_has_header: bool | None = None
    include_deleted: bool | None = None
    report_items_limit: int | None = None
    dataset: str | None = None
    vault_file: str | None = None


def handler(ctx: CommandContext, opts: Options) -> CommandResult:
    """
    Назначение:
        Запустить сценарий import-plan через CLI handler.
    """
    settings = ctx.settings
    run_id = ctx.run_id

    conn = None
    try:
        dataset_name, _spec = build_dataset_spec(opts.dataset, settings)
        conn, _engine, _cache_repo, _cache_specs = build_cache(settings)

        include_deleted_value = opts.include_deleted if opts.include_deleted is not None else settings.include_deleted
        report_items_limit_value = (
            opts.report_items_limit if opts.report_items_limit is not None else settings.report_items_limit
        )
        csv_has_header_value = opts.csv_has_header if opts.csv_has_header is not None else settings.csv_has_header

        service = ImportPlanService()
        return service.run(
            conn=conn,
            csv_has_header=csv_has_header_value,
            include_deleted=include_deleted_value,
            settings=settings,
            dataset=dataset_name,
            logger=ctx.logger,
            run_id=run_id,
            report_items_limit=report_items_limit_value,
            report_dir=settings.report_dir,
            vault_file=opts.vault_file,
        )
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        return _result_with(SystemErrorCode.INTERNAL_ERROR)
    except Exception as exc:
        logEvent(ctx.logger, logging.ERROR, run_id, "plan", f"Import plan failed: {exc}")
        typer.echo("ERROR: import plan failed (see logs)", err=True)
        return _result_with(SystemErrorCode.INTERNAL_ERROR)
    finally:
        if conn is not None:
            conn.close()


def _result_with(code: SystemErrorCode) -> CommandResult:
    result = CommandResult()
    result.add_code(code)
    return result


__all__ = ["handler", "Options"]
