from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from connector.delivery.cli.context import CommandContext
from connector.delivery.commands.common import sqlite_cache_error_result
from connector.delivery.cli.bootstrap import (
    build_cache,
    build_dataset_spec,
    build_diagnostics_catalog,
    open_secret_store,
    build_pipeline_context,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.usecases.enrich_usecase import EnrichUseCase


@dataclass(frozen=True)
class Options:
    csv_has_header: bool | None = None
    dataset: str | None = None
    report_items_limit: int | None = None
    include_enriched_items: bool | None = None
    vault_file: str | None = None


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
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
    include_enriched_items_value = opts.include_enriched_items if opts.include_enriched_items is not None else True

    dataset_name, dataset_spec = build_dataset_spec(opts.dataset, app_settings.dataset)
    catalog = ctx.catalog or build_diagnostics_catalog(
        dataset_name,
        strict=app_settings.observability.diagnostics_strict,
    )
    report.set_meta(dataset=dataset_name, items_limit=report_items_limit_value)

    gateway = None
    try:
        gateway, cache_roles, _cache_specs = build_cache(app_settings.paths)
        with open_secret_store(
            paths_settings=app_settings.paths,
            enabled=bool(opts.vault_file),
        ) as secret_store:
            pipeline_ctx = build_pipeline_context(
                dataset_spec=dataset_spec,
                dataset_name=dataset_name,
                cache_roles=cache_roles,
                pending_settings=app_settings.pending,
                observability_settings=app_settings.observability,
                catalog=catalog,
                csv_has_header=csv_has_header_value,
                secret_store=secret_store,
            )
            usecase = EnrichUseCase(
                report_items_limit=report_items_limit_value,
                include_enriched_items=include_enriched_items_value,
            )
            return usecase.run(
                row_source=pipeline_ctx.row_source,
                map_stage=pipeline_ctx.map_stage,
                normalize_stage=pipeline_ctx.normalize_stage,
                enrich_stage=pipeline_ctx.enrich_stage,
                dataset=dataset_name,
                logger=ctx.logger,
                run_id=run_id,
                report=report,
                catalog=catalog,
            )
    except sqlite3.Error as exc:
        return sqlite_cache_error_result(logger=ctx.logger, run_id=run_id, scope="enrich", exc=exc)
    finally:
        if gateway is not None:
            gateway.close()


__all__ = ["handler", "Options"]
