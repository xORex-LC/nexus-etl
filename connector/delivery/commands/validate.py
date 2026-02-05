from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.cli.bootstrap import (
    build_cache,
    build_dataset_spec,
    build_diagnostics_catalog,
    build_pipeline_context,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.stages.stages import StagePipeline, MapStage, NormalizeStage, EnrichStage
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.logging.setup import logEvent
from connector.usecases.validate_usecase import ValidateUseCase
from connector.domain.validation.validator import logValidationFailure


@dataclass(frozen=True)
class Options:
    csv_path: str | None = None
    csv_has_header: bool | None = None


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    """
    Назначение:
        Запустить validate сценарий через delivery-команду.
    """
    run_id = ctx.run_id
    settings = ctx.settings
    csv_has_header_value = opts.csv_has_header if opts.csv_has_header is not None else settings.csv_has_header

    dataset_name, dataset_spec = build_dataset_spec(None, settings)
    catalog = ctx.catalog or build_diagnostics_catalog(dataset_name, strict=settings.diagnostics_strict)

    conn = None
    try:
        conn, _engine, _cache_repo, _cache_specs = build_cache(settings)

        pipeline_ctx = build_pipeline_context(
            dataset_spec=dataset_spec,
            dataset_name=dataset_name,
            conn=conn,
            settings=settings,
            catalog=catalog,
            csv_path=opts.csv_path or "",
            csv_has_header=csv_has_header_value,
        )
        report_items_limit = pipeline_ctx.report_items_limit
        report.set_meta(dataset=dataset_name, items_limit=report_items_limit)
        validate_usecase = ValidateUseCase(
            report_items_limit=report_items_limit,
            include_valid_items=False,
        )
        enrich_pipeline = StagePipeline(
            [
                pipeline_ctx.map_stage,
                pipeline_ctx.normalize_stage,
                pipeline_ctx.enrich_stage,
            ]
        )
        return validate_usecase.run(
            enriched_source=enrich_pipeline.run(
                Extractor(pipeline_ctx.row_source, catalog=pipeline_ctx.catalog).run()
            ),
            validator=pipeline_ctx.validator,
            dataset=dataset_name,
            logger=ctx.logger,
            run_id=run_id,
            report=report,
            log_failure=logValidationFailure,
            catalog=catalog,
        )
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
