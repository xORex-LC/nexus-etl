from __future__ import annotations

from pathlib import Path

import typer

from connector.config.config import loadSettings
from connector.common.run_id import generate_run_id
from connector.delivery.cli.context import CommandContext, CommandPaths
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli.runtime import run_with_report
from connector.delivery.cli import options as cli_options
from connector.delivery.cli.bootstrap import build_diagnostics_catalog
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

app = typer.Typer(no_args_is_help=True, add_completion=False)
cacheApp = typer.Typer(no_args_is_help=True)
importApp = typer.Typer(no_args_is_help=True)
userApp = typer.Typer(no_args_is_help=True)


def _ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def _build_ctx(ctx: typer.Context, dataset: str | None = None) -> CommandContext:
    settings = ctx.obj["settings"]
    catalog = build_diagnostics_catalog(dataset, strict=settings.diagnostics_strict)
    return CommandContext(
        settings=settings,
        logger=ctx.obj["logger"],
        run_id=ctx.obj["runId"],
        catalog=catalog,
        strict=settings.diagnostics_strict,
        paths=CommandPaths(report_dir=settings.report_dir, work_dir=None),
        extra={"sources": ctx.obj.get("sources")},
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
    resourceExistsRetries: int | None = typer.Option(None, "--resource-exists-retries", help="Retries for resourceExists"),
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
        "resource_exists_retries": resourceExistsRetries,
        "report_include_skipped": None,
        "diagnostics_strict": strictDiagnostics,
    }
    loaded = loadSettings(config_path=config, cli_overrides=cliOverrides)

    _ensure_dir(loaded.settings.log_dir)
    _ensure_dir(loaded.settings.report_dir)
    _ensure_dir(loaded.settings.cache_dir)

    ctx.obj = {
        "runId": runId,
        "settings": loaded.settings,
        "sources": loaded.sources_used,
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
    command_ctx = _build_ctx(ctx, dataset)
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
    command_ctx = _build_ctx(ctx, dataset)
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
    command_ctx = _build_ctx(ctx, dataset)
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
    command_ctx = _build_ctx(ctx, dataset)
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
    vaultFile: str | None = cli_options.VAULT_FILE,
):
    opts = enrich_command.Options(
        csv_has_header=csvHasHeader,
        dataset=dataset,
        report_items_limit=reportItemsLimit,
        include_enriched_items=includeEnrichedItems,
        vault_file=vaultFile,
    )
    command_ctx = _build_ctx(ctx, dataset)
    run_with_report(
        ctx=command_ctx,
        command_name="enrich",
        opts=opts,
        handler=enrich_command.handler,
        requirements=Requirements(requires_source=True, requires_dataset=True, requires_cache=True),
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
    vaultFile: str | None = cli_options.VAULT_FILE,
):
    opts = import_plan_command.Options(
        csv_has_header=csvHasHeader,
        include_deleted=includeDeleted,
        report_items_limit=reportItemsLimit,
        dataset=dataset,
        vault_file=vaultFile,
    )
    command_ctx = _build_ctx(ctx, dataset)
    run_with_report(
        ctx=command_ctx,
        command_name="import-plan",
        opts=opts,
        handler=import_plan_command.handler,
        requirements=Requirements(requires_source=True, requires_dataset=True, requires_cache=True),
    )


@importApp.command("apply")
def importApply(
    ctx: typer.Context,
    plan: str | None = typer.Option(None, "--plan", help="Path to plan_import.json"),
    stopOnFirstError: bool | None = cli_options.STOP_ON_FIRST_ERROR,
    maxActions: int | None = cli_options.MAX_ACTIONS,
    dryRun: bool | None = cli_options.DRY_RUN,
    resourceExistsRetries: int | None = cli_options.RESOURCE_EXISTS_RETRIES,
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
    secretsFrom: str | None = cli_options.SECRETS_FROM,
    vaultFile: str | None = cli_options.VAULT_FILE,
):
    opts = import_apply_command.Options(
        plan_path=plan,
        stop_on_first_error=stopOnFirstError,
        max_actions=maxActions,
        dry_run=dryRun,
        report_items_limit=reportItemsLimit,
        resource_exists_retries=resourceExistsRetries,
        secrets_from=secretsFrom,
        vault_file=vaultFile,
    )
    command_ctx = _build_ctx(ctx)
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
    command_ctx = _build_ctx(ctx)
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
    reportItemsLimit: int | None = cli_options.REPORT_ITEMS_LIMIT,
):
    settings = ctx.obj["settings"]
    opts = cache_refresh_command.Options(
        page_size=pageSize if pageSize is not None else settings.page_size,
        max_pages=maxPages if maxPages is not None else settings.max_pages,
        timeout_seconds=timeoutSeconds,
        retries=retries,
        retry_backoff_seconds=retryBackoffSeconds,
        include_deleted=includeDeleted,
        report_items_limit=reportItemsLimit,
        dataset=dataset,
        api_transport=None,
    )
    command_ctx = _build_ctx(ctx, dataset)
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
    command_ctx = _build_ctx(ctx, dataset)
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
):
    opts = cache_clear_command.Options(dataset=dataset)
    command_ctx = _build_ctx(ctx, dataset)
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
