from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.cli.pipeline_config import CheckpointName
from connector.delivery.commands.common import sqlite_cache_error_result
from connector.delivery.cli.containers import (
    build_dataset_spec,
    build_diagnostics_catalog,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.usecases.mapping_usecase import MappingUseCase


@dataclass(frozen=True)
class Options:
    csv_has_header: bool | None = None
    dataset: str | None = None
    report_items_limit: int | None = None
    include_mapped_items: bool | None = None


def handler(ctx: BoundCommandContext, opts: Options, report) -> CommandResult:
    run_id = ctx.run_id
    app_settings = ctx.app_settings
    if app_settings is None:
        raise ValueError("App settings are not initialized")

    csv_has_header_value = (
        opts.csv_has_header if opts.csv_has_header is not None else app_settings.dataset.csv_has_header
    )
    report_items_limit_value = (
        opts.report_items_limit
        if opts.report_items_limit is not None
        else app_settings.observability.report_items_limit
    )
    include_mapped_items_value = opts.include_mapped_items if opts.include_mapped_items is not None else True

    dataset_name, dataset_spec = build_dataset_spec(opts.dataset, app_settings.dataset)
    catalog = ctx.catalog or build_diagnostics_catalog(
        dataset_name,
        strict=app_settings.observability.diagnostics_strict,
    )
    report.set_meta(dataset=dataset_name, items_limit=report_items_limit_value)

    try:
        pipeline = ctx.container.pipeline
        composer = pipeline.pipeline_composer()
        with pipeline.dataset_spec.override(dataset_spec), \
             pipeline.run_id.override(run_id), \
             pipeline.csv_has_header.override(csv_has_header_value), \
             pipeline.catalog.override(catalog):
            usecase = MappingUseCase(
                report_items_limit=report_items_limit_value,
                include_mapped_items=include_mapped_items_value,
            )
            return usecase.run(
                row_source=pipeline.row_source(),
                pipeline=composer.compose(CheckpointName.MAP),
                dataset=dataset_name,
                logger=ctx.logger,
                run_id=run_id,
                report=report,
                catalog=catalog,
            )
    except sqlite3.Error as exc:
        return sqlite_cache_error_result(logger=ctx.logger, run_id=run_id, scope="mapping", exc=exc)


__all__ = ["handler", "Options"]
