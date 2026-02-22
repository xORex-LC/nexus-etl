from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.commands.common import sqlite_cache_error_result
from connector.delivery.cli.containers import (
    build_dataset_spec,
    build_diagnostics_catalog,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.stages.stages import StagePipeline
from connector.usecases.planning_match_runtime import open_match_runtime


@dataclass(frozen=True)
class Options:
    csv_has_header: bool | None = None
    dataset: str | None = None
    report_items_limit: int | None = None
    include_matched_items: bool | None = None
    include_deleted: bool | None = None


def handler(ctx: BoundCommandContext, opts: Options, report) -> CommandResult:
    """
    Назначение:
        Запустить match сценарий через delivery-команду.
    """
    run_id = ctx.run_id
    app_settings = ctx.app_settings
    if app_settings is None:
        raise ValueError("App settings are not initialized")

    dataset_name, dataset_spec = build_dataset_spec(opts.dataset, app_settings.dataset)
    catalog = ctx.catalog or build_diagnostics_catalog(
        dataset_name,
        strict=app_settings.observability.diagnostics_strict,
    )

    csv_has_header_value = (
        opts.csv_has_header if opts.csv_has_header is not None else app_settings.dataset.csv_has_header
    )
    include_deleted_value = (
        opts.include_deleted if opts.include_deleted is not None else app_settings.dataset.include_deleted
    )
    report_items_limit_value = (
        opts.report_items_limit
        if opts.report_items_limit is not None
        else app_settings.observability.report_items_limit
    )
    include_matched_items_value = (
        opts.include_matched_items if opts.include_matched_items is not None else False
    )

    try:
        pipeline = ctx.container.pipeline
        with pipeline.dataset_spec.override(dataset_spec), \
             pipeline.run_id.override(run_id), \
             pipeline.csv_has_header.override(csv_has_header_value), \
             pipeline.catalog.override(catalog), \
             pipeline.include_deleted.override(include_deleted_value):
            map_stage = pipeline.map_stage()
            normalize_stage = pipeline.normalize_stage()
            enrich_stage = pipeline.enrich_stage()
            match_stage = pipeline.match_stage()

            row_source = pipeline.row_source()
            stage_pipeline = StagePipeline([map_stage, normalize_stage, enrich_stage])
            enriched_rows = iter_ok(
                stage_pipeline.run(Extractor(row_source, catalog=catalog).run()),
                should_skip=lambda item: item.row is None,
            )

            planning_runtime = ctx.container.cache.roles().planning_runtime

            with open_match_runtime(
                run_id=run_id,
                match_stage=match_stage,
                match_runtime=planning_runtime,
                report_items_limit=report_items_limit_value,
                include_matched_items=include_matched_items_value,
                batch_size=app_settings.matching_runtime.match_batch_size,
                flush_interval_ms=app_settings.matching_runtime.match_flush_interval_ms,
            ) as match_runtime:
                return match_runtime.match_usecase.run(
                    enriched_source=enriched_rows,
                    match_stage=match_runtime.match_stage,
                    dataset=dataset_name,
                    report=report,
                    run_scope=match_runtime.runtime_scope,
                )
    except sqlite3.Error as exc:
        return sqlite_cache_error_result(logger=ctx.logger, run_id=run_id, scope="match", exc=exc)


__all__ = ["handler", "Options"]
