from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from connector.config.app_settings import load_app_settings
from connector.config.config import SettingsLoadError
from connector.config.diagnostics import translate_settings_load_error
from connector.common.run_id import generate_run_id
from connector.delivery.cli.context import CommandPaths, CommandContext, UnboundCommandContext
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli.runtime import run_with_report
from connector.delivery.cli import options as cli_options
from connector.delivery.cli.containers import build_diagnostics_catalog
from connector.delivery.cli.settings_slice_map import (
    COMMAND_SETTINGS_SLICE_MAP,
    COMMAND_TO_USECASE,
    USECASE_SETTINGS_SLICE_MAP,
)
from connector.delivery.commands import (
    cache_clear as cache_clear_command,
    cache_refresh as cache_refresh_command,
    cache_status as cache_status_command,
    check_api as check_api_command,
    enrich as enrich_command,
    import_apply as import_apply_command,
    import_plan as import_plan_command,
    match as match_command,
    mapping as mapping_command,
    normalize as normalize_command,
    resolve as resolve_command,
)
from connector.domain.models import DiagnosticStage

app = typer.Typer(no_args_is_help=True, add_completion=False)
cacheApp = typer.Typer(no_args_is_help=True)
importApp = typer.Typer(no_args_is_help=True)
userApp = typer.Typer(no_args_is_help=True)


def _ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def _build_ctx(
    ctx: typer.Context,
    dataset: str | None = None,
    *,
    command_key: str | None = None,
) -> UnboundCommandContext:
    app_settings = ctx.obj.get("app_settings")
    if app_settings is None:
        raise RuntimeError("App settings are not initialized")
    catalog = build_diagnostics_catalog(dataset, strict=app_settings.observability.diagnostics_strict)
    extra: dict[str, Any] = {"sources": ctx.obj.get("sources")}
    if command_key:
        usecase_name = COMMAND_TO_USECASE.get(command_key)
        extra["settings_contract"] = {
            "command_key": command_key,
            "command_slices": [t.__name__ for t in COMMAND_SETTINGS_SLICE_MAP.get(command_key, ())],
            "usecase": usecase_name,
            "usecase_slices": [t.__name__ for t in USECASE_SETTINGS_SLICE_MAP.get(usecase_name, ())] if usecase_name else [],
        }
    return CommandContext(
        logger=ctx.obj["logger"],
        run_id=ctx.obj["runId"],
        catalog=catalog,
        strict=app_settings.observability.diagnostics_strict,
        app_settings=app_settings,
        container=None,
        paths=CommandPaths(report_dir=app_settings.paths.report_dir, work_dir=None),
        extra=extra,
    )


@app.callback()
def main(
    ctx: typer.Context,
    config: str | None = typer.Option(None, "--config", help="Path to config.yml"),
    runId: str | None = typer.Option(None, "--run-id", help="Run identifier (UUID). If omitted, generated."),
    logLevel: str | None = typer.Option(None, "--log-level", help="Log level: ERROR|WARN|INFO|DEBUG"),
    logJson: bool | None = typer.Option(None, "--log-json", help="Enable JSON logging (reserved)"),
    logDir: str | None = typer.Option(None, "--log-dir", help="Directory for logs."),
    reportDir: str | None = typer.Option(None, "--report-dir", help="Directory for reports."),
    cacheDir: str | None = typer.Option(None, "--cache-dir", help="Directory for cache (SQLite later)."),
    host: str | None = typer.Option(None, "--host", help="API host/IP"),
    port: int | None = typer.Option(None, "--port", help="API port"),
    apiUsername: str | None = typer.Option(None, "--api-username", help="API username"),
    apiPassword: str | None = typer.Option(None, "--api-password", help="API password (avoid; use env/file)"),
    apiPasswordFile: str | None = typer.Option(None, "--api-password-file", help="Read API password from file"),
    tlsSkipVerify: bool | None = typer.Option(None, "--tls-skip-verify", help="Disable TLS verification"),
    caFile: str | None = typer.Option(None, "--ca-file", help="CA file path"),
    pageSize: int | None = typer.Option(None, "--page-size", help="Page size for API pagination"),
    maxPages: int | None = typer.Option(None, "--max-pages", help="Max pages to fetch from API"),
    timeoutSeconds: float | None = typer.Option(None, "--timeout-seconds", help="API timeout in seconds"),
    retries: int | None = typer.Option(None, "--retries", help="Retry attempts for API calls"),
    retryBackoffSeconds: float | None = typer.Option(None, "--retry-backoff-seconds", help="Base backoff for retries"),
    matchBatchSize: int | None = typer.Option(None, "--match-batch-size", help="Match micro-batch size"),
    matchFlushIntervalMs: int | None = typer.Option(
        None,
        "--match-flush-interval-ms",
        help="Match micro-batch flush interval (ms)",
    ),
    resolveBatchSize: int | None = typer.Option(None, "--resolve-batch-size", help="Resolve micro-batch size"),
    resolveFlushIntervalMs: int | None = typer.Option(
        None,
        "--resolve-flush-interval-ms",
        help="Resolve micro-batch flush interval (ms)",
    ),
    strictDiagnostics: bool | None = typer.Option(
        None,
        "--strict-diagnostics/--no-strict-diagnostics",
        help="Fail on unknown diagnostic codes",
    ),
):
    if apiPasswordFile and not apiPassword:
        p = Path(apiPasswordFile)
        if not p.exists() or not p.is_file():
            typer.echo(f"ERROR: api-password-file not found: {apiPasswordFile}", err=True)
            raise typer.Exit(code=2)
        apiPassword = p.read_text(encoding="utf-8").strip()

    if not runId:
        runId = generate_run_id()

    cliOverrides = {
        "host": host,
        "port": port,
        "api_username": apiUsername,
        "api_password": apiPassword,
        "log_level": logLevel,
        "log_json": logJson,
        "log_dir": logDir,
        "report_dir": reportDir,
        "cache_dir": cacheDir,
        "tls_skip_verify": tlsSkipVerify,
        "ca_file": caFile,
        "page_size": pageSize,
        "max_pages": maxPages,
        "timeout_seconds": timeoutSeconds,
        "retries": retries,
        "retry_backoff_seconds": retryBackoffSeconds,
        "match_batch_size": matchBatchSize,
        "match_flush_interval_ms": matchFlushIntervalMs,
        "resolve_batch_size": resolveBatchSize,
        "resolve_flush_interval_ms": resolveFlushIntervalMs,
        "report_include_skipped": None,
        "diagnostics_strict": strictDiagnostics,
    }
    try:
        loaded_app = load_app_settings(config_path=config, cli_overrides=cliOverrides)
    except SettingsLoadError as exc:
        catalog = build_diagnostics_catalog(None, strict=False)
        diagnostics = translate_settings_load_error(
            catalog=catalog,
            stage=DiagnosticStage.SINK,
            error=exc,
            record_ref=None,
        )
        typer.echo("ERROR: invalid settings configuration", err=True)
        for diag in diagnostics:
            field = f" ({diag.field})" if diag.field else ""
            typer.echo(f"- [{diag.code}]{field} {diag.message}", err=True)
        raise typer.Exit(code=2) from exc
    _ensure_dir(loaded_app.app_settings.paths.log_dir)
    _ensure_dir(loaded_app.app_settings.paths.report_dir)
    _ensure_dir(loaded_app.app_settings.paths.cache_dir)

    ctx.obj = {
        "runId": runId,
        "app_settings": loaded_app.app_settings,
        "sources": list(loaded_app.sources_used),
        "settings_source_trace": loaded_app.source_trace,
        "configPath": config,
        "logger": None,
    }


@app.command("mapping")
def mapping(
    ctx: typer.Context,
    csvHasHeader: bool | None = cli_options.CSV_HAS_HEADER,
    dataset: str | None = cli_options.DATASET,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    includeMappedItems: bool | None = typer.Option(
        None,
        "--include-mapped-items/--no-include-mapped-items",
        help="Include mapped rows in report items",
        show_default=True,
    ),
):
    opts = mapping_command.Options(
        csv_has_header=csvHasHeader,
        dataset=dataset,
        report_items_limit=reportItemsLimit,
        include_mapped_items=includeMappedItems,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="mapping")
    run_with_report(
        ctx=command_ctx,
        command_name="mapping",
        opts=opts,
        handler=mapping_command.handler,
        requirements=Requirements(requires_source=True, requires_dataset=True, requires_cache=True),
    )


@app.command("match")
def match(
    ctx: typer.Context,
    csvHasHeader: bool | None = cli_options.CSV_HAS_HEADER,
    dataset: str | None = cli_options.DATASET,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    includeMatchedItems: bool | None = typer.Option(
        None,
        "--include-matched-items/--no-include-matched-items",
        help="Include matched rows in report items",
        show_default=True,
    ),
    includeDeleted: bool | None = cli_options.INCLUDE_DELETED,
):
    opts = match_command.Options(
        csv_has_header=csvHasHeader,
        dataset=dataset,
        report_items_limit=reportItemsLimit,
        include_matched_items=includeMatchedItems,
        include_deleted=includeDeleted,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="match")
    run_with_report(
        ctx=command_ctx,
        command_name="match",
        opts=opts,
        handler=match_command.handler,
        requirements=Requirements(requires_source=True, requires_dataset=True, requires_cache=True),
    )


@app.command("normalize")
def normalize(
    ctx: typer.Context,
    csvHasHeader: bool | None = cli_options.CSV_HAS_HEADER,
    dataset: str | None = cli_options.DATASET,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    includeNormalizedItems: bool | None = typer.Option(
        None,
        "--include-normalized-items/--no-include-normalized-items",
        help="Include normalized rows in report items",
        show_default=True,
    ),
):
    opts = normalize_command.Options(
        csv_has_header=csvHasHeader,
        dataset=dataset,
        report_items_limit=reportItemsLimit,
        include_normalized_items=includeNormalizedItems,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="normalize")
    run_with_report(
        ctx=command_ctx,
        command_name="normalize",
        opts=opts,
        handler=normalize_command.handler,
        requirements=Requirements(requires_source=True, requires_dataset=True, requires_cache=True),
    )


@app.command("resolve")
def resolve(
    ctx: typer.Context,
    csvHasHeader: bool | None = cli_options.CSV_HAS_HEADER,
    dataset: str | None = cli_options.DATASET,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    includeResolvedItems: bool | None = typer.Option(
        None,
        "--include-resolved-items/--no-include-resolved-items",
        help="Include resolved rows in report items",
        show_default=True,
    ),
    includeDeleted: bool | None = cli_options.INCLUDE_DELETED,
):
    opts = resolve_command.Options(
        csv_has_header=csvHasHeader,
        dataset=dataset,
        report_items_limit=reportItemsLimit,
        include_resolved_items=includeResolvedItems,
        include_deleted=includeDeleted,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="resolve")
    run_with_report(
        ctx=command_ctx,
        command_name="resolve",
        opts=opts,
        handler=resolve_command.handler,
        requirements=Requirements(requires_source=True, requires_dataset=True, requires_cache=True),
    )


@app.command("enrich")
def enrich(
    ctx: typer.Context,
    csvHasHeader: bool | None = cli_options.CSV_HAS_HEADER,
    dataset: str | None = cli_options.DATASET,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    includeEnrichedItems: bool | None = typer.Option(
        None,
        "--include-enriched-items/--no-include-enriched-items",
        help="Include enriched rows in report items",
        show_default=True,
    ),
    vaultMode: str | None = cli_options.VAULT_MODE,
):
    opts = enrich_command.Options(
        csv_has_header=csvHasHeader,
        dataset=dataset,
        report_items_limit=reportItemsLimit,
        include_enriched_items=includeEnrichedItems,
        vault_mode=vaultMode,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="enrich")
    run_with_report(
        ctx=command_ctx,
        command_name="enrich",
        opts=opts,
        handler=enrich_command.handler,
        requirements=Requirements(
            requires_source=True,
            requires_dataset=True,
            requires_cache=True,
            requires_dictionaries=True,
        ),
    )


@importApp.command("plan")
def importPlan(
    ctx: typer.Context,
    csvHasHeader: bool | None = cli_options.CSV_HAS_HEADER,
    includeDeleted: bool | None = cli_options.INCLUDE_DELETED,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    reportIncludeSkipped: bool | None = typer.Option(
        None,
        "--report-include-skipped/--no-report-include-skipped",
        help="Include skipped rows in plan report",
        show_default=True,
    ),
    dataset: str | None = cli_options.DATASET,
    vaultMode: str | None = cli_options.VAULT_MODE,
):
    opts = import_plan_command.Options(
        csv_has_header=csvHasHeader,
        include_deleted=includeDeleted,
        report_items_limit=reportItemsLimit,
        dataset=dataset,
        vault_mode=vaultMode,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="import-plan")
    run_with_report(
        ctx=command_ctx,
        command_name="import-plan",
        opts=opts,
        handler=import_plan_command.handler,
        requirements=Requirements(
            requires_source=True,
            requires_dataset=True,
            requires_cache=True,
            requires_dictionaries=True,
        ),
    )


@importApp.command("apply")
def importApply(
    ctx: typer.Context,
    plan: str | None = typer.Option(None, "--plan", help="Path to plan_import.json"),
    stopOnFirstError: bool | None = cli_options.STOP_ON_FIRST_ERROR,
    maxActions: int | None = cli_options.MAX_ACTIONS,
    dryRun: bool | None = cli_options.DRY_RUN,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    vaultMode: str | None = cli_options.VAULT_MODE,
):
    opts = import_apply_command.Options(
        plan_path=plan,
        stop_on_first_error=stopOnFirstError,
        max_actions=maxActions,
        dry_run=dryRun,
        report_items_limit=reportItemsLimit,
        vault_mode=vaultMode,
    )
    command_ctx = _build_ctx(ctx, command_key="import-apply")
    run_with_report(
        ctx=command_ctx,
        command_name="import-apply",
        opts=opts,
        handler=import_apply_command.handler,
        requirements=Requirements(requires_api=True, requires_cache=True),
    )


@app.command("check-api")
def checkApi(ctx: typer.Context):
    opts = check_api_command.Options(api_transport=None)
    command_ctx = _build_ctx(ctx, command_key="check-api")
    run_with_report(
        ctx=command_ctx,
        command_name="check-api",
        opts=opts,
        handler=check_api_command.handler,
        requirements=Requirements(requires_api=True),
    )


@cacheApp.command("refresh")
def cacheRefresh(
    ctx: typer.Context,
    pageSize: int | None = typer.Option(None, "--page-size", help="Page size for API pagination"),
    maxPages: int | None = typer.Option(None, "--max-pages", help="Maximum pages to fetch from API"),
    timeoutSeconds: float | None = cli_options.TIMEOUT_SECONDS,
    retries: int | None = cli_options.RETRIES,
    retryBackoffSeconds: float | None = cli_options.RETRY_BACKOFF_SECONDS,
    dataset: str | None = cli_options.DATASET,
    includeDeleted: bool | None = cli_options.INCLUDE_DELETED,
    deps: bool | None = typer.Option(
        None,
        "--deps/--no-deps",
        help="Include dataset dependencies in refresh scope (defaults to cache policy)",
    ),
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
):
    app_settings = ctx.obj.get("app_settings")
    if app_settings is None:
        raise RuntimeError("App settings are not initialized")
    opts = cache_refresh_command.Options(
        page_size=pageSize if pageSize is not None else app_settings.refresh.page_size,
        max_pages=maxPages if maxPages is not None else app_settings.refresh.max_pages,
        timeout_seconds=timeoutSeconds,
        retries=retries,
        retry_backoff_seconds=retryBackoffSeconds,
        include_deleted=includeDeleted,
        include_dependencies=deps,
        report_items_limit=reportItemsLimit,
        dataset=dataset,
        api_transport=None,
    )
    command_ctx = _build_ctx(ctx, dataset, command_key="cache-refresh")
    run_with_report(
        ctx=command_ctx,
        command_name="cache-refresh",
        opts=opts,
        handler=cache_refresh_command.handler,
        requirements=Requirements(requires_api=True, requires_cache=True),
    )


@cacheApp.command("status")
def cacheStatus(
    ctx: typer.Context,
    dataset: str | None = cli_options.DATASET,
):
    opts = cache_status_command.Options(dataset=dataset)
    command_ctx = _build_ctx(ctx, dataset, command_key="cache-status")
    run_with_report(
        ctx=command_ctx,
        command_name="cache-status",
        opts=opts,
        handler=cache_status_command.handler,
        requirements=Requirements(requires_cache=True),
    )


@cacheApp.command("clear")
def cacheClear(
    ctx: typer.Context,
    dataset: str | None = cli_options.DATASET,
    cascade: bool | None = typer.Option(
        None,
        "--cascade/--no-cascade",
        help="Cascade clear to dependent datasets (defaults to cache policy)",
    ),
):
    opts = cache_clear_command.Options(dataset=dataset, cascade=cascade)
    command_ctx = _build_ctx(ctx, dataset, command_key="cache-clear")
    run_with_report(
        ctx=command_ctx,
        command_name="cache-clear",
        opts=opts,
        handler=cache_clear_command.handler,
        requirements=Requirements(requires_cache=True),
    )


app.add_typer(cacheApp, name="cache")
app.add_typer(importApp, name="import")
app.add_typer(userApp, name="user")
