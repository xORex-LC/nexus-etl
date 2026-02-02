from __future__ import annotations

import logging
import sqlite3

import typer

from connector.delivery.bootstrap import build_diagnostics_catalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.datasets.registry import get_spec
from connector.domain.validation.deps import ValidationDependencies
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.datasets.cache_registry import list_cache_specs
from connector.infra.cache.db import openCacheDb, getCacheDbPath
from connector.infra.logging.setup import logEvent
from connector.usecases.enrich_usecase import EnrichUseCase
from connector.usecases.validate_usecase import ValidateUseCase
from connector.domain.validation.validator import logValidationFailure


def run(
    *,
    ctx: typer.Context,
    csv_path: str | None,
    csv_has_header: bool | None,
    logger,
    report,
) -> CommandResult:
    """
    Назначение:
        Запустить validate сценарий через delivery-команду.
    """
    run_id = ctx.obj["runId"]
    settings = ctx.obj["settings"]
    csv_has_header_value = csv_has_header if csv_has_header is not None else settings.csv_has_header
    dataset_name = settings.dataset_name

    catalog = build_diagnostics_catalog(dataset_name, strict=settings.diagnostics_strict)

    dataset_spec = get_spec(dataset_name)
    try:
        conn = openCacheDb(getCacheDbPath(settings.cache_dir))
    except sqlite3.Error as exc:
        logEvent(logger, logging.ERROR, run_id, "cache", f"Failed to open cache DB: {exc}")
        typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
        return _result_with(SystemErrorCode.CACHE_ERROR)
    try:
        engine = SqliteEngine(conn)
        cache_specs = dataset_spec.build_cache_specs()
        ensure_cache_ready(engine, cache_specs)

        deps = dataset_spec.build_validation_deps(conn, settings)
        enrich_deps = dataset_spec.build_enrich_deps(conn, settings, secret_store=None)
        transform_bundle = dataset_spec.build_transformers(deps, enrich_deps, catalog)
        transformer = transform_bundle.build_pipeline(catalog)
        validator_bundle = dataset_spec.build_validator(deps, catalog)
        validator = validator_bundle.validator
        report_items_limit = settings.report_items_limit
        report.set_meta(dataset=dataset_name, items_limit=report_items_limit)
        row_source = dataset_spec.build_record_source(
            csv_path=csv_path,
            csv_has_header=csv_has_header_value,
        )

        enrich_usecase = EnrichUseCase(
            report_items_limit=report_items_limit,
            include_enriched_items=False,
        )
        enriched_ok = enrich_usecase.iter_enriched_ok(
            row_source=row_source,
            transformer=transformer,
            catalog=catalog,
        )
        validate_usecase = ValidateUseCase(
            report_items_limit=report_items_limit,
            include_valid_items=False,
        )
        return validate_usecase.run(
            enriched_source=enriched_ok,
            validator=validator,
            dataset=dataset_name,
            logger=logger,
            run_id=run_id,
            report=report,
            log_failure=logValidationFailure,
            catalog=catalog,
        )
    finally:
        conn.close()


def _result_with(code: SystemErrorCode) -> CommandResult:
    result = CommandResult()
    result.add_code(code)
    return result


__all__ = ["run"]
