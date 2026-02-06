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
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.iterators import iter_ok
from connector.infra.logging.setup import logEvent
from connector.usecases.match_usecase import MatchUseCase
from connector.usecases.resolve_usecase import ResolveUseCase
from connector.domain.transform.matching.deduplication_transform import DeduplicationTransform
from connector.domain.transform.matching.lookup_enricher import LookupEnricher


@dataclass(frozen=True)
class Options:
    csv_has_header: bool | None = None
    dataset: str | None = None
    report_items_limit: int | None = None
    include_resolved_items: bool | None = None
    include_deleted: bool | None = None


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    """
    Назначение:
        Запустить resolve сценарий через delivery-команду.
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
    include_resolved_items_value = (
        opts.include_resolved_items if opts.include_resolved_items is not None else False
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

        cache_repo = planning_deps.cache_repo
        if cache_repo is None:
            raise ValueError("planning cache_repo is not configured")
        if planning_deps.identity_repo is None:
            raise ValueError("planning identity_repo is not configured")
        if planning_deps.pending_repo is None:
            raise ValueError("planning pending_repo is not configured")

        matcher = DeduplicationTransform(
            dataset=dataset_name,
            cache_repo=cache_repo,
            matching_rules=planning_bundle.matching_rules,
            resolve_rules=planning_bundle.resolve_rules,
            include_deleted=include_deleted_value,
            catalog=catalog,
        )
        match_usecase = MatchUseCase(
            report_items_limit=report_items_limit_value,
            include_matched_items=False,
        )
        matched_rows = iter_ok(
            match_usecase.iter_matched(
                enriched_source=enriched_rows,
                matcher=matcher,
                catalog=catalog,
            ),
            should_skip=lambda r: any(w.code == "MATCH_DUPLICATE_SOURCE" for w in r.warnings),
        )

        resolver = LookupEnricher(
            planning_bundle.resolve_rules,
            planning_bundle.link_rules,
            identity_repo=planning_deps.identity_repo,
            pending_repo=planning_deps.pending_repo,
            settings=planning_deps.resolver_settings,
            catalog=catalog,
        )
        resolve_usecase = ResolveUseCase(
            report_items_limit=report_items_limit_value,
            include_resolved_items=include_resolved_items_value,
        )
        return resolve_usecase.run(
            matched_source=matched_rows,
            resolver=resolver,
            dataset=dataset_name,
            report=report,
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
