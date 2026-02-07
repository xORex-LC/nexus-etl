from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from connector.delivery.cli.context import CommandContext
from connector.delivery.commands.common import sqlite_cache_error_result
from connector.delivery.cli.bootstrap import (
    build_cache,
    build_dataset_spec,
    build_diagnostics_catalog,
    build_pipeline_context,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.iterators import iter_ok
from connector.usecases.planning_match_runtime import open_match_runtime


@dataclass(frozen=True)
class Options:
    csv_has_header: bool | None = None
    dataset: str | None = None
    report_items_limit: int | None = None
    include_matched_items: bool | None = None
    include_deleted: bool | None = None


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    """
    Назначение:
        Запустить match сценарий через delivery-команду.
    """
    run_id = ctx.run_id
    settings = ctx.settings

    dataset_name, dataset_spec = build_dataset_spec(opts.dataset, settings)
    catalog = ctx.catalog or build_diagnostics_catalog(dataset_name, strict=settings.diagnostics_strict)

    csv_has_header_value = opts.csv_has_header if opts.csv_has_header is not None else settings.csv_has_header
    include_deleted_value = opts.include_deleted if opts.include_deleted is not None else settings.include_deleted
    report_items_limit_value = (
        opts.report_items_limit if opts.report_items_limit is not None else settings.report_items_limit
    )
    include_matched_items_value = (
        opts.include_matched_items if opts.include_matched_items is not None else False
    )

    conn = None
    try:
        conn, _engine, _cache_repo, _cache_specs = build_cache(settings)

        pipeline_ctx = build_pipeline_context(
            dataset_spec=dataset_spec,
            dataset_name=dataset_name,
            conn=conn,
            settings=settings,
            catalog=catalog,
            csv_has_header=csv_has_header_value,
        )
        planning_deps = pipeline_ctx.planning_deps
        enriched_rows = iter_ok(
            pipeline_ctx.stage_pipeline.run(Extractor(pipeline_ctx.row_source, catalog=pipeline_ctx.catalog).run()),
            should_skip=lambda item: item.row is None,
        )

        planning_bundle = dataset_spec.build_planning_bundle()

        with open_match_runtime(
            dataset=dataset_name,
            include_deleted=include_deleted_value,
            run_id=run_id,
            planning_deps=planning_deps,
            planning_bundle=planning_bundle,
            catalog=catalog,
            report_items_limit=report_items_limit_value,
            include_matched_items=include_matched_items_value,
            batch_size=settings.match_batch_size,
            flush_interval_ms=settings.match_flush_interval_ms,
        ) as match_runtime:
            return match_runtime.match_usecase.run(
                enriched_source=enriched_rows,
                matcher=match_runtime.matcher,
                dataset=dataset_name,
                report=report,
                catalog=catalog,
                run_scope=match_runtime.runtime_scope,
            )
    except sqlite3.Error as exc:
        return sqlite_cache_error_result(logger=ctx.logger, run_id=run_id, scope="match", exc=exc)
    finally:
        if conn is not None:
            conn.close()


__all__ = ["handler", "Options"]
