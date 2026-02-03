from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.cli.bootstrap import build_cache, build_dataset_spec, build_diagnostics_catalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.validation.deps import ValidationDependencies
from connector.infra.logging.setup import logEvent
from connector.infra.secrets.file_vault_provider import FileVaultSecretStore
from connector.usecases.enrich_usecase import EnrichUseCase


@dataclass(frozen=True)
class Options:
    csv_path: str | None = None
    csv_has_header: bool | None = None
    dataset: str | None = None
    report_items_limit: int | None = None
    include_enriched_items: bool | None = None
    vault_file: str | None = None


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    run_id = ctx.run_id
    settings = ctx.settings
    csv_has_header_value = opts.csv_has_header if opts.csv_has_header is not None else settings.csv_has_header
    report_items_limit_value = (
        opts.report_items_limit if opts.report_items_limit is not None else settings.report_items_limit
    )
    include_enriched_items_value = opts.include_enriched_items if opts.include_enriched_items is not None else True

    deps = ValidationDependencies()
    dataset_name, dataset_spec = build_dataset_spec(opts.dataset, settings)
    catalog = ctx.catalog or build_diagnostics_catalog(dataset_name, strict=settings.diagnostics_strict)
    report.set_meta(dataset=dataset_name, items_limit=report_items_limit_value)

    conn = None
    try:
        conn, _engine, _cache_repo, _cache_specs = build_cache(settings)
        secret_store = FileVaultSecretStore(opts.vault_file) if opts.vault_file else None
        enrich_deps = dataset_spec.build_enrich_deps(conn, settings, secret_store=secret_store)
        transform_bundle = dataset_spec.build_transformers(deps, enrich_deps, catalog)
        transformer = transform_bundle.build_pipeline(catalog)

        row_source = dataset_spec.build_record_source(
            csv_path=opts.csv_path,
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
            logger=ctx.logger,
            run_id=run_id,
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
