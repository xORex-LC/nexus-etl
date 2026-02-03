from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.cli.bootstrap import build_cache, build_dataset_spec, build_diagnostics_catalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.logging.setup import logEvent
from connector.usecases.enrich_usecase import EnrichUseCase
from connector.usecases.validate_usecase import ValidateUseCase
from connector.usecases.match_usecase import MatchUseCase
from connector.usecases.resolve_usecase import ResolveUseCase
from connector.domain.planning.matcher import Matcher
from connector.domain.planning.resolver import Resolver


@dataclass(frozen=True)
class Options:
    csv_path: str | None = None
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

        validation_deps = dataset_spec.build_validation_deps(conn, settings)
        enrich_deps = dataset_spec.build_enrich_deps(conn, settings, secret_store=None)
        planning_deps = dataset_spec.build_planning_deps(conn, settings)

        transform_bundle = dataset_spec.build_transformers(validation_deps, enrich_deps, catalog)
        transformer = transform_bundle.build_pipeline(catalog)
        validator_bundle = dataset_spec.build_validator(validation_deps, catalog)
        validator = validator_bundle.validator

        row_source = dataset_spec.build_record_source(
            csv_path=opts.csv_path,
            csv_has_header=csv_has_header_value,
        )

        enrich_usecase = EnrichUseCase(
            report_items_limit=report_items_limit_value,
            include_enriched_items=False,
        )
        enriched_ok = enrich_usecase.iter_enriched_ok(
            row_source=row_source,
            transformer=transformer,
            catalog=catalog,
        )

        validate_usecase = ValidateUseCase(
            report_items_limit=report_items_limit_value,
            include_valid_items=False,
        )
        validated_rows = validate_usecase.iter_validated_ok(
            enriched_source=enriched_ok,
            validator=validator,
            catalog=catalog,
        )

        matching_rules = dataset_spec.build_matching_rules()
        resolve_rules = dataset_spec.build_resolve_rules()
        link_rules = dataset_spec.build_link_rules()

        cache_repo = planning_deps.cache_repo
        if cache_repo is None:
            raise ValueError("planning cache_repo is not configured")
        if planning_deps.identity_repo is None:
            raise ValueError("planning identity_repo is not configured")
        if planning_deps.pending_repo is None:
            raise ValueError("planning pending_repo is not configured")

        matcher = Matcher(
            dataset=dataset_name,
            cache_repo=cache_repo,
            matching_rules=matching_rules,
            resolve_rules=resolve_rules,
            include_deleted=include_deleted_value,
            catalog=catalog,
        )
        match_usecase = MatchUseCase(
            report_items_limit=report_items_limit_value,
            include_matched_items=False,
        )
        matched_rows = match_usecase.iter_matched_ok(
            validated_source=validated_rows,
            matcher=matcher,
            catalog=catalog,
        )

        resolver = Resolver(
            resolve_rules,
            link_rules,
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
