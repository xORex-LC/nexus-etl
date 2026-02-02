from __future__ import annotations

import logging
import sqlite3
import sys
import time
from pathlib import Path

import typer

from connector.infra.cache.db import getCacheDbPath, openCacheDb
from connector.config.config import Settings, loadSettings
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.logging.setup import StdStreamToLogger, TeeStream, createCommandLogger, logEvent
from connector.delivery.commands import import_plan as import_plan_command
from connector.delivery.commands import import_apply as import_apply_command
from connector.delivery.commands import validate as validate_command
from connector.delivery.commands import mapping as mapping_command
from connector.delivery.commands import normalize as normalize_command
from connector.delivery.commands import enrich as enrich_command
from connector.delivery.commands import cache_refresh as cache_refresh_command
from connector.delivery.commands import cache_status as cache_status_command
from connector.delivery.commands import cache_clear as cache_clear_command
from connector.delivery.commands import check_api as check_api_command
from connector.infra.artifacts.report_writer import createEmptyReport, finalizeReport, writeReportJson
from connector.common.sanitize import maskSecret
from connector.common.time import getDurationMs
from connector.common.run_id import generate_run_id
from connector.datasets.registry import resolve_dataset_name

app = typer.Typer(no_args_is_help=True, add_completion=False)
cacheApp = typer.Typer(no_args_is_help=True)
importApp = typer.Typer(no_args_is_help=True)
userApp = typer.Typer(no_args_is_help=True)  # резерв под будущие команды

def ensureDir(path: str) -> None:
    """
    Назначение:
        Создаёт каталог, если он отсутствует.

    Входные данные:
        path: str
            Путь к каталогу.

    Выходные данные:
        None

    Алгоритм:
        - Path(path).mkdir(parents=True, exist_ok=True)
    """
    Path(path).mkdir(parents=True, exist_ok=True)

def requireCsv(csvPath: str | None) -> None:
    """
    Назначение:
        Базовая проверка наличия CSV-файла (требование ТЗ для import/validate).

    Входные данные:
        csvPath: str | None
            Путь к CSV.

    Выходные данные:
        None

    Поведение:
        - Если csvPath не задан или файл не существует — завершает процесс с exit code 2.
    """
    if not csvPath:
        typer.echo("ERROR: --csv is required", err=True)
        raise typer.Exit(code=2)

    p = Path(csvPath)
    if not p.exists() or not p.is_file():
        typer.echo(f"ERROR: CSV file not found: {csvPath}", err=True)
        raise typer.Exit(code=2)

def requireApi(settings: Settings) -> None:
    """
    Назначение:
        Проверяет наличие параметров API для команд, которым нужен REST доступ.

    Входные данные:
        settings: Settings
            Итоговые настройки после мерджа.

    Выходные данные:
        None

    Поведение:
        - Если чего-то не хватает — exit code 2.
    """
    missing = []
    if not settings.host:
        missing.append("host")
    if not settings.port:
        missing.append("port")
    if not settings.api_username:
        missing.append("api_username")
    if not settings.api_password:
        missing.append("api_password")

    if missing:
        typer.echo(f"ERROR: missing API settings: {', '.join(missing)}", err=True)
        raise typer.Exit(code=2)

def printRunHeader(runId: str, command: str, settings: Settings, sources: list[str]) -> None:
    """
    Назначение:
        Печатает безопасную сводку параметров запуска (без секретов).

    Входные данные:
        runId: str
        command: str
        settings: Settings
        sources: list[str]

    Выходные данные:
        None
    """
    typer.echo(
        f"run_id={runId} command={command} "
        f"host={settings.host} port={settings.port} api_username={settings.api_username} "
        f"api_password={maskSecret(settings.api_password)} sources={sources}"
        f" log_level={settings.log_level} log_json={settings.log_json} "
    )


def _result_with(code: SystemErrorCode, summary: dict | None = None) -> CommandResult:
    result = CommandResult(summary=summary)
    result.add_code(code)
    return result


def _result_ok(summary: dict | None = None) -> CommandResult:
    return _result_with(SystemErrorCode.OK, summary=summary)

def runWithReport(
    ctx: typer.Context,
    commandName: str,
    csvPath: str | None,
    requiresCsv: bool,
    requiresApiAccess: bool,
    runner,
) -> None:
    """
    Назначение:
        Унифицированная обвязка выполнения команд:
        - создаёт логгер + файл лога
        - создаёт report.json skeleton
        - валидирует обязательные входы (CSV/API)
        - перенаправляет stdout/stderr в лог (tee)
        - гарантирует запись отчёта в finally

    Входные данные:
        ctx: typer.Context
        commandName: str
        csvPath: str | None
        requiresCsv: bool
        requiresApiAccess: bool

    Выходные данные:
        None

    Поведение:
        - На ошибках обязательных параметров: пишет ошибку в лог и report и завершает exit code 2.
    """
    runId = ctx.obj["runId"]
    settings: Settings = ctx.obj["settings"]
    sources = ctx.obj["sources"]

    startMonotonic = time.monotonic()

    logger, logFilePath = createCommandLogger(
        commandName=commandName,
        logDir=settings.log_dir,
        runId=runId,
        logLevel=settings.log_level,
    )

    report = createEmptyReport(runId=runId, command=commandName, configSources=sources)
    if csvPath:
        report.set_context("input", {"csv_path": Path(csvPath).name})

    originalStdout = sys.stdout
    originalStderr = sys.stderr

    stdoutLoggerStream = StdStreamToLogger(logger, logging.INFO, runId, "stdout")
    stderrLoggerStream = StdStreamToLogger(logger, logging.ERROR, runId, "stderr")

    sys.stdout = TeeStream(originalStdout, stdoutLoggerStream)
    sys.stderr = TeeStream(originalStderr, stderrLoggerStream)

    exit_result: int | CommandResult | None = None

    try:
        logEvent(logger, logging.INFO, runId, "core", "Command started")
        printRunHeader(runId, commandName, settings, sources)

        if requiresApiAccess:
            try:
                requireApi(settings)
            except typer.Exit:
                logEvent(logger, logging.ERROR, runId, "config", "Missing API settings")
                typer.echo("ERROR: missing API settings (see logs/report)", err=True)
                exit_result = _result_with(SystemErrorCode.INTERNAL_ERROR)
                return

        if requiresCsv:
            try:
                requireCsv(csvPath)
            except typer.Exit:
                logEvent(logger, logging.ERROR, runId, "csv", "CSV is missing or not accessible")
                typer.echo("ERROR: invalid or missing CSV (see logs/report)", err=True)
                exit_result = _result_with(SystemErrorCode.IO_ERROR)
                return

        exit_result = runner(logger, report)

    finally:
        durationMs = getDurationMs(startMonotonic, time.monotonic())
        finalizeReport(
            report=report,
            durationMs=durationMs,
            logFile=logFilePath,
            cacheDir=settings.cache_dir,
            reportDir=settings.report_dir,
        )
        reportPath = writeReportJson(report, settings.report_dir, f"report_{commandName}_{runId}")
        logEvent(logger, logging.INFO, runId, "report", f"Report written: {reportPath}")

        sys.stdout = originalStdout
        sys.stderr = originalStderr

        if exit_result is not None:
            if hasattr(exit_result, "exit_code"):
                raise typer.Exit(code=exit_result.exit_code())
            raise typer.Exit(code=exit_result)


def runWithoutReport(
    ctx: typer.Context,
    commandName: str,
    csvPath: str | None,
    requiresCsv: bool,
    requiresApiAccess: bool,
    runner,
) -> None:
    """
    Назначение:
        Обвязка выполнения команд без формирования отчёта (только лог).
    """
    runId = ctx.obj["runId"]
    settings: Settings = ctx.obj["settings"]
    sources = ctx.obj["sources"]

    startMonotonic = time.monotonic()
    logger, logFilePath = createCommandLogger(
        commandName=commandName,
        logDir=settings.log_dir,
        runId=runId,
        logLevel=settings.log_level,
    )

    originalStdout = sys.stdout
    originalStderr = sys.stderr

    stdoutLoggerStream = StdStreamToLogger(logger, logging.INFO, runId, "stdout")
    stderrLoggerStream = StdStreamToLogger(logger, logging.ERROR, runId, "stderr")

    sys.stdout = TeeStream(originalStdout, stdoutLoggerStream)
    sys.stderr = TeeStream(originalStderr, stderrLoggerStream)

    exit_result: int | CommandResult | None = None

    try:
        logEvent(logger, logging.INFO, runId, "core", "Command started")
        printRunHeader(runId, commandName, settings, sources)

        if requiresApiAccess:
            try:
                requireApi(settings)
            except typer.Exit:
                logEvent(logger, logging.ERROR, runId, "config", "Missing API settings")
                typer.echo("ERROR: missing API settings (see logs)", err=True)
                exit_result = _result_with(SystemErrorCode.INTERNAL_ERROR)
                return

        if requiresCsv:
            try:
                requireCsv(csvPath)
            except typer.Exit:
                logEvent(logger, logging.ERROR, runId, "csv", "CSV is missing or not accessible")
                typer.echo("ERROR: invalid or missing CSV (see logs)", err=True)
                exit_result = _result_with(SystemErrorCode.IO_ERROR)
                return

        exit_result = runner(logger)

    finally:
        _ = getDurationMs(startMonotonic, time.monotonic())
        logEvent(logger, logging.INFO, runId, "log", f"Log written: {logFilePath}")
        sys.stdout = originalStdout
        sys.stderr = originalStderr

        if exit_result is not None:
            if hasattr(exit_result, "exit_code"):
                raise typer.Exit(code=exit_result.exit_code())
            raise typer.Exit(code=exit_result)

def runCacheRefreshCommand(
    ctx: typer.Context,
    pageSize: int | None,
    maxPages: int | None,
    timeoutSeconds: float | None,
    retries: int | None,
    retryBackoffSeconds: float | None,
    apiTransport=None,
    includeDeleted: bool | None = None,
    reportItemsLimit: int | None = None,
    dataset: str | None = None,
) -> None:
    settings: Settings = ctx.obj["settings"]
    runId = ctx.obj["runId"]

    def execute(logger, report):
        return cache_refresh_command.run(
            ctx=ctx,
            page_size=pageSize,
            max_pages=maxPages,
            timeout_seconds=timeoutSeconds,
            retries=retries,
            retry_backoff_seconds=retryBackoffSeconds,
            api_transport=apiTransport,
            include_deleted=includeDeleted,
            report_items_limit=reportItemsLimit,
            dataset=dataset,
            logger=logger,
            report=report,
        )

    runWithReport(
        ctx=ctx,
        commandName="cache-refresh",
        csvPath=None,
        requiresCsv=False,
        requiresApiAccess=True,
        runner=execute,
    )

def runCacheStatusCommand(ctx: typer.Context, dataset: str | None = None) -> None:
    def execute(logger, report):
        return cache_status_command.run(
            ctx=ctx,
            dataset=dataset,
            logger=logger,
            report=report,
        )

    runWithReport(
        ctx=ctx,
        commandName="cache-status",
        csvPath=None,
        requiresCsv=False,
        requiresApiAccess=False,
        runner=execute,
    )

def runCacheClearCommand(ctx: typer.Context, dataset: str | None = None) -> None:
    def execute(logger, report):
        return cache_clear_command.run(
            ctx=ctx,
            dataset=dataset,
            logger=logger,
            report=report,
        )

    runWithReport(
        ctx=ctx,
        commandName="cache-clear",
        csvPath=None,
        requiresCsv=False,
        requiresApiAccess=False,
        runner=execute,
    )

def runImportPlanCommand(
    ctx: typer.Context,
    csvPath: str | None,
    csvHasHeader: bool | None,
    includeDeleted: bool | None,
    reportItemsLimit: int | None,
    reportIncludeSkipped: bool | None,
    dataset: str | None,
    vaultFile: str | None,
) -> None:
    def execute(logger):
        return import_plan_command.run(
            ctx=ctx,
            csv_path=csvPath,
            csv_has_header=csvHasHeader,
            include_deleted=includeDeleted,
            report_items_limit=reportItemsLimit,
            dataset=dataset,
            vault_file=vaultFile,
            logger=logger,
        )

    runWithoutReport(
        ctx=ctx,
        commandName="import-plan",
        csvPath=csvPath,
        requiresCsv=True,
        requiresApiAccess=False,
        runner=execute,
    )

def runImportApplyCommand(
    ctx: typer.Context,
    planPath: str | None,
    stopOnFirstError: bool | None,
    maxActions: int | None,
    dryRun: bool | None,
    reportItemsLimit: int | None,
    resourceExistsRetries: int | None,
    secretsFrom: str | None,
    vaultFile: str | None,
) -> None:
    def execute(logger, report):
        return import_apply_command.run(
            ctx=ctx,
            plan_path=planPath,
            stop_on_first_error=stopOnFirstError,
            max_actions=maxActions,
            dry_run=dryRun,
            report_items_limit=reportItemsLimit,
            resource_exists_retries=resourceExistsRetries,
            secrets_from=secretsFrom,
            vault_file=vaultFile,
            logger=logger,
            report=report,
        )

    runWithReport(
        ctx=ctx,
        commandName="import-apply",
        csvPath=None,
        requiresCsv=False,
        requiresApiAccess=True,
        runner=execute,
    )
def runCheckApiCommand(ctx: typer.Context, apiTransport=None) -> None:
    def execute(logger, report):
        return check_api_command.run(
            ctx=ctx,
            api_transport=apiTransport,
            logger=logger,
            report=report,
        )

    runWithReport(
        ctx=ctx,
        commandName="check-api",
        csvPath=None,
        requiresCsv=False,
        requiresApiAccess=True,
        runner=execute,
    )

def runValidateCommand(ctx: typer.Context, csvPath: str | None, csvHasHeader: bool | None) -> None:
    def execute(logger, report):
        return validate_command.run(
            ctx=ctx,
            csv_path=csvPath,
            csv_has_header=csvHasHeader,
            logger=logger,
            report=report,
        )

    runWithReport(
        ctx=ctx,
        commandName="validate",
        csvPath=csvPath,
        requiresCsv=True,
        requiresApiAccess=False,
        runner=execute,
    )

def runMappingCommand(
    ctx: typer.Context,
    csvPath: str | None,
    csvHasHeader: bool | None,
    dataset: str | None,
    reportItemsLimit: int | None,
    includeMappedItems: bool | None,
) -> None:
    def execute(logger, report):
        return mapping_command.run(
            ctx=ctx,
            csv_path=csvPath,
            csv_has_header=csvHasHeader,
            dataset=dataset,
            report_items_limit=reportItemsLimit,
            include_mapped_items=includeMappedItems,
            logger=logger,
            report=report,
        )

    runWithReport(
        ctx=ctx,
        commandName="mapping",
        csvPath=csvPath,
        requiresCsv=True,
        requiresApiAccess=False,
        runner=execute,
    )

def runNormalizeCommand(
    ctx: typer.Context,
    csvPath: str | None,
    csvHasHeader: bool | None,
    dataset: str | None,
    reportItemsLimit: int | None,
    includeNormalizedItems: bool | None,
) -> None:
    def execute(logger, report):
        return normalize_command.run(
            ctx=ctx,
            csv_path=csvPath,
            csv_has_header=csvHasHeader,
            dataset=dataset,
            report_items_limit=reportItemsLimit,
            include_normalized_items=includeNormalizedItems,
            logger=logger,
            report=report,
        )

    runWithReport(
        ctx=ctx,
        commandName="normalize",
        csvPath=csvPath,
        requiresCsv=True,
        requiresApiAccess=False,
        runner=execute,
    )


def runEnrichCommand(
    ctx: typer.Context,
    csvPath: str | None,
    csvHasHeader: bool | None,
    dataset: str | None,
    reportItemsLimit: int | None,
    includeEnrichedItems: bool | None,
    vaultFile: str | None,
) -> None:
    def execute(logger, report):
        return enrich_command.run(
            ctx=ctx,
            csv_path=csvPath,
            csv_has_header=csvHasHeader,
            dataset=dataset,
            report_items_limit=reportItemsLimit,
            include_enriched_items=includeEnrichedItems,
            vault_file=vaultFile,
            logger=logger,
            report=report,
        )

    runWithReport(
        ctx=ctx,
        commandName="enrich",
        csvPath=csvPath,
        requiresCsv=True,
        requiresApiAccess=False,
        runner=execute,
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
    """
    Назначение:
        Глобальная инициализация CLI:
        - генерирует/принимает run_id
        - загружает настройки (CLI > ENV > config > defaults)
        - создаёт каталоги log/report/cache
        - сохраняет всё в ctx.obj для подкоманд

    Входные данные:
        Параметры CLI, описанные в ТЗ (Блок 4).

    Выходные данные:
        None (но записывает данные в ctx.obj).
    """
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
        "report_include_skipped": None,  # set per-command in runImportPlanCommand
        "diagnostics_strict": strictDiagnostics,
    }
    loaded = loadSettings(config_path=config, cli_overrides=cliOverrides)

    ensureDir(loaded.settings.log_dir)
    ensureDir(loaded.settings.report_dir)
    ensureDir(loaded.settings.cache_dir)

    ctx.obj = {
        "runId": runId,
        "settings": loaded.settings,
        "sources": loaded.sources_used,
        "configPath": config,
    }

@app.command()
def validate(
    ctx: typer.Context,
    csv: str | None = typer.Option(None, "--csv", help="Path to input CSV"),
    csvHasHeader: bool | None = typer.Option(None, "--csv-has-header", help="CSV includes header row"),
):
    runValidateCommand(ctx, csv, csvHasHeader)

@app.command("mapping")
def mapping(
    ctx: typer.Context,
    csv: str | None = typer.Option(None, "--csv", help="Path to input CSV"),
    csvHasHeader: bool | None = typer.Option(None, "--csv-has-header", help="CSV includes header row"),
    dataset: str | None = typer.Option(None, "--dataset", help="Dataset name (e.g., employees)", show_default=True),
    reportItemsLimit: int | None = typer.Option(None, "--report-items-limit", help="Limit report items stored"),
    includeMappedItems: bool | None = typer.Option(
        None,
        "--include-mapped-items/--no-include-mapped-items",
        help="Include mapped rows in report items",
        show_default=True,
    ),
):
    runMappingCommand(
        ctx=ctx,
        csvPath=csv,
        csvHasHeader=csvHasHeader,
        dataset=dataset,
        reportItemsLimit=reportItemsLimit,
        includeMappedItems=includeMappedItems,
    )

@app.command("normalize")
def normalize(
    ctx: typer.Context,
    csv: str | None = typer.Option(None, "--csv", help="Path to input CSV"),
    csvHasHeader: bool | None = typer.Option(None, "--csv-has-header", help="CSV includes header row"),
    dataset: str | None = typer.Option(None, "--dataset", help="Dataset name (e.g., employees)", show_default=True),
    reportItemsLimit: int | None = typer.Option(None, "--report-items-limit", help="Limit report items stored"),
    includeNormalizedItems: bool | None = typer.Option(
        None,
        "--include-normalized-items/--no-include-normalized-items",
        help="Include normalized rows in report items",
        show_default=True,
    ),
):
    runNormalizeCommand(
        ctx=ctx,
        csvPath=csv,
        csvHasHeader=csvHasHeader,
        dataset=dataset,
        reportItemsLimit=reportItemsLimit,
        includeNormalizedItems=includeNormalizedItems,
    )

@app.command("enrich")
def enrich(
    ctx: typer.Context,
    csv: str | None = typer.Option(None, "--csv", help="Path to input CSV"),
    csvHasHeader: bool | None = typer.Option(None, "--csv-has-header", help="CSV includes header row"),
    dataset: str | None = typer.Option(None, "--dataset", help="Dataset name (e.g., employees)", show_default=True),
    reportItemsLimit: int | None = typer.Option(None, "--report-items-limit", help="Limit report items stored"),
    includeEnrichedItems: bool | None = typer.Option(
        None,
        "--include-enriched-items/--no-include-enriched-items",
        help="Include enriched rows in report items",
        show_default=True,
    ),
    vaultFile: str | None = typer.Option(None, "--vault-file", help="Path to secrets vault CSV"),
):
    runEnrichCommand(
        ctx=ctx,
        csvPath=csv,
        csvHasHeader=csvHasHeader,
        dataset=dataset,
        reportItemsLimit=reportItemsLimit,
        includeEnrichedItems=includeEnrichedItems,
        vaultFile=vaultFile,
    )

@importApp.command("plan")
def importPlan(
    ctx: typer.Context,
    csv: str | None = typer.Option(None, "--csv", help="Path to input CSV"),
    csvHasHeader: bool | None = typer.Option(None, "--csv-has-header", help="CSV includes header row"),
    includeDeleted: bool | None = typer.Option(
        None,
        "--include-deleted/--no-include-deleted",
        help="Include deleted users in matching",
        show_default=True,
    ),
    reportItemsLimit: int | None = typer.Option(None, "--report-items-limit", help="Limit report items stored"),
    reportIncludeSkipped: bool | None = typer.Option(
        None,
        "--report-include-skipped/--no-report-include-skipped",
        help="Include skipped rows in plan report",
        show_default=True,
    ),
    dataset: str | None = typer.Option(
        None,
        "--dataset",
        help="Dataset name (e.g., employees)",
        show_default=True,
    ),
    vaultFile: str | None = typer.Option(None, "--vault-file", help="Path to secrets vault CSV"),
):
    runImportPlanCommand(
        ctx=ctx,
        csvPath=csv,
        csvHasHeader=csvHasHeader,
        includeDeleted=includeDeleted,
        reportItemsLimit=reportItemsLimit,
        reportIncludeSkipped=reportIncludeSkipped,
        dataset=dataset,
        vaultFile=vaultFile,
    )

@importApp.command("apply")
def importApply(
    ctx: typer.Context,
    plan: str | None = typer.Option(None, "--plan", help="Path to plan_import.json"),
    stopOnFirstError: bool | None = typer.Option(
        None,
        "--stop-on-first-error/--no-stop-on-first-error",
        help="Stop on first failed apply",
        show_default=True,
    ),
    maxActions: int | None = typer.Option(None, "--max-actions", help="Limit number of actions to apply"),
    dryRun: bool | None = typer.Option(None, "--dry-run/--no-dry-run", help="Do not send API requests"),
    resourceExistsRetries: int | None = typer.Option(
        None,
        "--resource-exists-retries",
        help="Retries for resourceExists on create",
    ),
    reportItemsLimit: int | None = typer.Option(None, "--report-items-limit", help="Limit report items stored"),
    secretsFrom: str | None = typer.Option(
        None,
        "--secrets-from",
        help="Secret source: none|prompt|vault",
        show_default=True,
    ),
    vaultFile: str | None = typer.Option(None, "--vault-file", help="Path to secrets vault CSV"),
):
    runImportApplyCommand(
        ctx=ctx,
        planPath=plan,
        stopOnFirstError=stopOnFirstError,
        maxActions=maxActions,
        dryRun=dryRun,
        reportItemsLimit=reportItemsLimit,
        resourceExistsRetries=resourceExistsRetries,
        secretsFrom=secretsFrom,
        vaultFile=vaultFile,
    )

@app.command("check-api")
def checkApi(ctx: typer.Context):
    runCheckApiCommand(ctx)

@cacheApp.command("refresh")
def cacheRefresh(
    ctx: typer.Context,
    pageSize: int | None = typer.Option(None, "--page-size", help="Page size for API pagination"),
    maxPages: int | None = typer.Option(None, "--max-pages", help="Maximum pages to fetch from API"),
    timeoutSeconds: float | None = typer.Option(None, "--timeout-seconds", help="API timeout in seconds"),
    retries: int | None = typer.Option(None, "--retries", help="Retry attempts for API requests"),
    retryBackoffSeconds: float | None = typer.Option(None, "--retry-backoff-seconds", help="Base backoff seconds for retries"),
    dataset: str | None = typer.Option(None, "--dataset", help="Limit refresh to a specific dataset"),
    includeDeleted: bool | None = typer.Option(
        None,
        "--include-deleted/--no-include-deleted",
        help="Include users with accountStatus=deleted or deletionDate set",
        show_default=True,
    ),
    reportItemsLimit: int | None = typer.Option(None, "--report-items-limit", help="Limit report items stored"),
):
    runCacheRefreshCommand(
        ctx=ctx,
        pageSize=pageSize if pageSize is not None else ctx.obj["settings"].page_size,
        maxPages=maxPages if maxPages is not None else ctx.obj["settings"].max_pages,
        timeoutSeconds=timeoutSeconds if timeoutSeconds is not None else ctx.obj["settings"].timeout_seconds,
        retries=retries if retries is not None else ctx.obj["settings"].retries,
        retryBackoffSeconds=retryBackoffSeconds if retryBackoffSeconds is not None else ctx.obj["settings"].retry_backoff_seconds,
        includeDeleted=includeDeleted if includeDeleted is not None else ctx.obj["settings"].include_deleted,
        reportItemsLimit=reportItemsLimit if reportItemsLimit is not None else ctx.obj["settings"].report_items_limit,
        dataset=dataset,
    )

@cacheApp.command("status")
def cacheStatus(
    ctx: typer.Context,
    dataset: str | None = typer.Option(None, "--dataset", help="Show status for a specific dataset"),
):
    runCacheStatusCommand(ctx, dataset=dataset)

@cacheApp.command("clear")
def cacheClear(
    ctx: typer.Context,
    dataset: str | None = typer.Option(None, "--dataset", help="Clear a specific dataset"),
):
    runCacheClearCommand(ctx, dataset=dataset)

app.add_typer(cacheApp, name="cache")
app.add_typer(importApp, name="import")
app.add_typer(userApp, name="user")
