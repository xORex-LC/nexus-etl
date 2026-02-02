from __future__ import annotations

import logging
import sqlite3

import typer

from connector.delivery.bootstrap import build_diagnostics_catalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.datasets.registry import get_spec, resolve_dataset_name
from connector.domain.validation.deps import ValidationDependencies
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.cache.db import openCacheDb, getCacheDbPath
from connector.infra.logging.setup import logEvent
from connector.infra.secrets.file_vault_provider import FileVaultSecretStore
from connector.usecases.enrich_usecase import EnrichUseCase


def run(
    *,
    ctx: typer.Context,
    csv_path: str | None,
    csv_has_header: bool | None,
    dataset: str | None,
    report_items_limit: int | None,
    include_enriched_items: bool | None,
    vault_file: str | None,
    logger,
    report,
) -> CommandResult:
    run_id = ctx.obj["runId"]
    settings = ctx.obj["settings"]
    csv_has_header_value = csv_has_header if csv_has_header is not None else settings.csv_has_header
    dataset_name = resolve_dataset_name(dataset, settings.dataset_name)
    report_items_limit_value = (
        report_items_limit if report_items_limit is not None else settings.report_items_limit
    )
    include_enriched_items_value = include_enriched_items if include_enriched_items is not None else True

    catalog = build_diagnostics_catalog(dataset_name, strict=settings.diagnostics_strict)

    deps = ValidationDependencies()
    dataset_spec = get_spec(dataset_name)
    report.set_meta(dataset=dataset_name, items_limit=report_items_limit_value)

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

        secret_store = FileVaultSecretStore(vault_file) if vault_file else None
        enrich_deps = dataset_spec.build_enrich_deps(conn, settings, secret_store=secret_store)
        transform_bundle = dataset_spec.build_transformers(deps, enrich_deps, catalog)
        transformer = transform_bundle.build_pipeline(catalog)

        row_source = dataset_spec.build_record_source(
            csv_path=csv_path,
            csv_has_header=csv_has_header_value,
        )
        usecase = EnrichUseCase(
            report_items_limit=report_items_limit_value,
            include_enriched_items=include_enriched_items_value,
        )
        return usecase.run(
            row_source=row_source,
            transformer=transformer,
            dataset=dataset_name,
            logger=logger,
            run_id=run_id,
            report=report,
            catalog=catalog,
        )
    finally:
        conn.close()


def _result_with(code: SystemErrorCode) -> CommandResult:
    result = CommandResult()
    result.add_code(code)
    return result


__all__ = ["run"]
