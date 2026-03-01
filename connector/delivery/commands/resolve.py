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
from connector.domain.transform.core.extractor import Extractor
from connector.domain.reporting.events import SetMetaEvent
from connector.domain.reporting.policy import ReportPolicy
from connector.usecases.resolve_usecase import ResolveUseCase


@dataclass(frozen=True)
class Options:
    csv_has_header: bool | None = None
    dataset: str | None = None
    report_items_limit: int | None = None
    include_resolved_items: bool | None = None
    include_deleted: bool | None = None


def handler(ctx: BoundCommandContext, opts: Options, report_sink) -> CommandResult:
    run_id = ctx.run_id
    app_config = ctx.app_config
    if app_config is None:
        raise ValueError("App settings are not initialized")

    dataset_name, dataset_spec = build_dataset_spec(opts.dataset, app_config.dataset)
    catalog = ctx.catalog or build_diagnostics_catalog(
        dataset_name,
        strict=app_config.observability.diagnostics_strict,
    )

    csv_has_header_value = (
        opts.csv_has_header if opts.csv_has_header is not None else app_config.dataset.csv_has_header
    )
    include_deleted_value = (
        opts.include_deleted if opts.include_deleted is not None else app_config.dataset.include_deleted
    )
    report_items_limit_value = (
        opts.report_items_limit
        if opts.report_items_limit is not None
        else app_config.observability.report_items_limit
    )
    include_resolved_items_value = (
        opts.include_resolved_items if opts.include_resolved_items is not None else False
    )
    report_sink.emit(SetMetaEvent(dataset=dataset_name))
    report_policy = ReportPolicy.from_profile(app_config.observability.report_policy_profile)

    try:
        pipeline = ctx.container.pipeline
        composer = pipeline.pipeline_composer()
        with pipeline.dataset_spec.override(dataset_spec), \
             pipeline.run_id.override(run_id), \
             pipeline.csv_has_header.override(csv_has_header_value), \
             pipeline.catalog.override(catalog), \
             pipeline.include_deleted.override(include_deleted_value):
            plan_hooks = pipeline.resolve_stage_hooks()
            row_source = pipeline.row_source()
            pre_resolve = composer.compose(CheckpointName.RESOLVE_CONTEXT, hooks=plan_hooks)
            contextualized = pre_resolve.run(Extractor(row_source, catalog=catalog).run())

            planning_runtime = ctx.container.cache.roles().planning_runtime

            resolve_usecase = ResolveUseCase(
                report_items_limit=report_items_limit_value,
                include_resolved_items=include_resolved_items_value,
                batch_size=app_config.resolver.resolve_batch_size,
                flush_interval_ms=app_config.resolver.resolve_flush_interval_ms,
            )
            return resolve_usecase.run(
                matched_source=contextualized,
                resolve_stage=pipeline.resolve_stage(),
                dataset=dataset_name,
                report_sink=report_sink,
                report_policy=report_policy,
                catalog=catalog,
                pending_expiry=pipeline.pending_expiry(),
                resolve_hooks=plan_hooks,
            )
    except sqlite3.Error as exc:
        return sqlite_cache_error_result(logger=ctx.logger, run_id=run_id, scope="resolve", exc=exc)


__all__ = ["handler", "Options"]
