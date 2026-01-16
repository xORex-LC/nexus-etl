from __future__ import annotations

import logging
import sqlite3
import sys
import time
import uuid
from pathlib import Path

import typer

from .ankeyApiClient import AnkeyApiClient, ApiError
from .cacheDb import ensureSchema, getCacheDbPath, openCacheDb
from .cacheCommandService import CacheCommandService
from .config import Settings, loadSettings
from .csvReader import CsvFormatError, readEmployeeRows
from .loggingSetup import StdStreamToLogger, TeeStream, createCommandLogger, logEvent
from .importApplyService import ImportApplyService, createUserApiClient, readPlanFromCsv
from .importPlanService import ImportPlanService
from .planReader import readPlanFile
from .interfaces import CacheCommandServiceProtocol, ImportPlanServiceProtocol
from .reporter import createEmptyReport, finalizeReport, writeReportJson
from .sanitize import maskSecret
from .timeUtils import getDurationMs
from .validator import ValidationContext, logValidationFailure, validateEmployeeRowWithContext

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
    report.meta.csv_path = csvPath

    originalStdout = sys.stdout
    originalStderr = sys.stderr

    stdoutLoggerStream = StdStreamToLogger(logger, logging.INFO, runId, "stdout")
    stderrLoggerStream = StdStreamToLogger(logger, logging.ERROR, runId, "stderr")

    sys.stdout = TeeStream(originalStdout, stdoutLoggerStream)
    sys.stderr = TeeStream(originalStderr, stderrLoggerStream)

    exitCode: int | None = None

    try:
        logEvent(logger, logging.INFO, runId, "core", "Command started")
        printRunHeader(runId, commandName, settings, sources)

        if requiresApiAccess:
            try:
                requireApi(settings)
            except typer.Exit:
                logEvent(logger, logging.ERROR, runId, "config", "Missing API settings")
                typer.echo("ERROR: missing API settings (see logs/report)", err=True)
                exitCode = 2
                return

        if requiresCsv:
            try:
                requireCsv(csvPath)
            except typer.Exit:
                logEvent(logger, logging.ERROR, runId, "csv", "CSV is missing or not accessible")
                typer.echo("ERROR: invalid or missing CSV (see logs/report)", err=True)
                exitCode = 2
                return

        exitCode = runner(logger, report)

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

        if exitCode is not None:
            raise typer.Exit(code=exitCode)


def runCacheRefreshCommand(
    ctx: typer.Context,
    pageSize: int | None,
    maxPages: int | None,
    timeoutSeconds: float | None,
    retries: int | None,
    retryBackoffSeconds: float | None,
    apiTransport=None,
    includeDeletedUsers: bool | None = None,
    reportItemsLimit: int | None = None,
    reportItemsSuccess: bool | None = None,
) -> None:
    settings: Settings = ctx.obj["settings"]
    runId = ctx.obj["runId"]
    cacheDbPath = getCacheDbPath(settings.cache_dir)

    def execute(logger, report) -> int:
        try:
            requireApi(settings)
        except typer.Exit:
            logEvent(logger, logging.ERROR, runId, "config", "Missing API settings")
            typer.echo("ERROR: missing API settings (see logs/report)", err=True)
            return 2
        report.meta.report_items_limit = reportItemsLimit if reportItemsLimit is not None else settings.report_items_limit
        report.meta.report_items_success = reportItemsSuccess if reportItemsSuccess is not None else settings.report_items_success
        try:
            conn = openCacheDb(cacheDbPath)
        except sqlite3.Error as exc:
            logEvent(logger, logging.ERROR, runId, "cache", f"Failed to open cache DB: {exc}")
            typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
            return 2

        try:
            service: CacheCommandServiceProtocol = CacheCommandService()
            return service.refresh(
                conn=conn,
                settings=settings,
                page_size=pageSize or settings.page_size,
                max_pages=maxPages or settings.max_pages,
                timeout_seconds=timeoutSeconds or settings.timeout_seconds,
                retries=retries or settings.retries,
                retry_backoff_seconds=retryBackoffSeconds or settings.retry_backoff_seconds,
                logger=logger,
                report=report,
                run_id=runId,
                api_transport=apiTransport,
                include_deleted_users=includeDeletedUsers if includeDeletedUsers is not None else settings.include_deleted_users,
                report_items_limit=reportItemsLimit or settings.report_items_limit,
                report_items_success=reportItemsSuccess if reportItemsSuccess is not None else settings.report_items_success,
            )
        except ValueError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            return 2
        except ApiError as exc:
            logEvent(logger, logging.ERROR, runId, "cache", f"Cache refresh failed: {exc}")
            typer.echo("ERROR: cache refresh failed (see logs/report)", err=True)
            return 2
        except Exception as exc:
            logEvent(logger, logging.ERROR, runId, "cache", f"Cache refresh failed: {exc}")
            typer.echo("ERROR: cache refresh failed (see logs/report)", err=True)
            return 2
        finally:
            conn.close()

    runWithReport(
        ctx=ctx,
        commandName="cache-refresh",
        csvPath=None,
        requiresCsv=False,
        requiresApiAccess=True,
        runner=execute,
    )


def runCacheStatusCommand(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj["settings"]
    runId = ctx.obj["runId"]
    cacheDbPath = getCacheDbPath(settings.cache_dir)

    def execute(logger, report) -> int:
        try:
            conn = openCacheDb(cacheDbPath)
        except sqlite3.Error as exc:
            logEvent(logger, logging.ERROR, runId, "cache", f"Failed to open cache DB: {exc}")
            typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
            return 2

        try:
            service: CacheCommandServiceProtocol = CacheCommandService()
            code, status = service.status(conn, logger, report, runId)
            if code != 0:
                typer.echo("ERROR: cache status failed (see logs/report)", err=True)
                return code
            typer.echo(
                "schema_version={schema_version} users={users_count} orgs={org_count} "
                "users_last_refresh_at={users_last_refresh_at} org_last_refresh_at={org_last_refresh_at}".format(
                    **status
                )
            )
            return 0
        finally:
            conn.close()

    runWithReport(
        ctx=ctx,
        commandName="cache-status",
        csvPath=None,
        requiresCsv=False,
        requiresApiAccess=False,
        runner=execute,
    )

def runCacheClearCommand(ctx: typer.Context) -> None:
    settings: Settings = ctx.obj["settings"]
    runId = ctx.obj["runId"]
    cacheDbPath = getCacheDbPath(settings.cache_dir)

    def execute(logger, report) -> int:
        try:
            conn = openCacheDb(cacheDbPath)
        except sqlite3.Error as exc:
            logEvent(logger, logging.ERROR, runId, "cache", f"Failed to open cache DB: {exc}")
            typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
            return 2

        try:
            service: CacheCommandServiceProtocol = CacheCommandService()
            code, _cleared = service.clear(conn, logger, report, runId)
            if code != 0:
                typer.echo("ERROR: cache clear failed (see logs/report)", err=True)
                return code
            return 0
        finally:
            conn.close()

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
    includeDeletedUsers: bool | None,
    onMissingOrg: str | None,
    reportItemsLimit: int | None,
    reportItemsSuccess: bool | None,
) -> None:
    settings: Settings = ctx.obj["settings"]
    runId = ctx.obj["runId"]
    cacheDbPath = getCacheDbPath(settings.cache_dir)

    def execute(logger, report) -> int:
        try:
            conn = openCacheDb(cacheDbPath)
        except sqlite3.Error as exc:
            logEvent(logger, logging.ERROR, runId, "cache", f"Failed to open cache DB: {exc}")
            typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
            return 2

        include_deleted = includeDeletedUsers if includeDeletedUsers is not None else settings.include_deleted_users
        on_missing = (onMissingOrg or settings.on_missing_org or "error").lower()
        report_items_limit = reportItemsLimit if reportItemsLimit is not None else settings.report_items_limit
        report_items_success = (
            reportItemsSuccess if reportItemsSuccess is not None else settings.report_items_success
        )
        csv_has_header = csvHasHeader if csvHasHeader is not None else settings.csv_has_header
        report.meta.report_items_limit = report_items_limit
        report.meta.report_items_success = report_items_success

        try:
            service: ImportPlanServiceProtocol = ImportPlanService()
            return service.run(
                conn=conn,
                csv_path=csvPath or "",
                csv_has_header=csv_has_header,
                include_deleted_users=include_deleted,
                on_missing_org=on_missing,
                logger=logger,
                run_id=runId,
                report=report,
                report_items_limit=report_items_limit,
                report_items_success=report_items_success,
                report_dir=settings.report_dir,
            )
        except ValueError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
            return 2
        except (CsvFormatError, OSError) as exc:
            logEvent(logger, logging.ERROR, runId, "plan", f"Import plan failed: {exc}")
            typer.echo(f"ERROR: import plan failed: {exc}", err=True)
            return 2
        except Exception as exc:
            logEvent(logger, logging.ERROR, runId, "plan", f"Import plan failed: {exc}")
            typer.echo("ERROR: import plan failed (see logs/report)", err=True)
            return 2
        finally:
            conn.close()

    runWithReport(
        ctx=ctx,
        commandName="import-plan",
        csvPath=csvPath,
        requiresCsv=True,
        requiresApiAccess=False,
        runner=execute,
    )


def runImportApplyCommand(
    ctx: typer.Context,
    csvPath: str | None,
    planPath: str | None,
    csvHasHeader: bool | None,
    stopOnFirstError: bool | None,
    maxActions: int | None,
    dryRun: bool | None,
    includeDeletedUsers: bool | None,
    onMissingOrg: str | None,
    reportItemsLimit: int | None,
    reportItemsSuccess: bool | None,
    resourceExistsRetries: int | None,
) -> None:
    settings: Settings = ctx.obj["settings"]
    runId = ctx.obj["runId"]
    cacheDbPath = getCacheDbPath(settings.cache_dir)

    def execute(logger, report) -> int:
        if (csvPath and planPath) or (not csvPath and not planPath):
            typer.echo("ERROR: specify exactly one of --csv or --plan", err=True)
            return 2

        include_deleted = includeDeletedUsers if includeDeletedUsers is not None else settings.include_deleted_users
        on_missing = (onMissingOrg or settings.on_missing_org or "error").lower()
        report_items_limit = reportItemsLimit if reportItemsLimit is not None else settings.report_items_limit
        report_items_success = (
            reportItemsSuccess if reportItemsSuccess is not None else settings.report_items_success
        )
        resource_exists_retries = (
            resourceExistsRetries if resourceExistsRetries is not None else settings.resource_exists_retries
        )
        csv_has_header = csvHasHeader if csvHasHeader is not None else settings.csv_has_header
        stop_on_first_error = (
            stopOnFirstError if stopOnFirstError is not None else settings.stop_on_first_error
        )
        max_actions = maxActions if maxActions is not None else settings.max_actions
        dry_run = dryRun if dryRun is not None else settings.dry_run

        plan = None
        conn = None
        try:
            if csvPath:
                try:
                    conn = openCacheDb(cacheDbPath)
                except sqlite3.Error as exc:
                    logEvent(logger, logging.ERROR, runId, "cache", f"Failed to open cache DB: {exc}")
                    typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
                    return 2
                plan = readPlanFromCsv(
                    conn=conn,
                    csv_path=csvPath,
                    csv_has_header=csv_has_header,
                    include_deleted_users=include_deleted,
                    on_missing_org=on_missing,
                    logger=logger,
                    run_id=runId,
                    report=report,
                    report_items_limit=report_items_limit,
                    report_items_success=report_items_success,
                    report_dir=settings.report_dir,
                )
                # Очистим report.items, чтобы в отчёте apply остались только результаты выполнения
                report.items = []
            else:
                plan = readPlanFile(planPath or "")
        except (CsvFormatError, OSError, ValueError) as exc:
            logEvent(logger, logging.ERROR, runId, "plan", f"Import apply failed: {exc}")
            typer.echo(f"ERROR: import apply failed: {exc}", err=True)
            return 2
        finally:
            if conn is not None:
                conn.close()

        if plan is None:
            typer.echo("ERROR: failed to load plan", err=True)
            return 2

        baseUrl = f"https://{settings.host}:{settings.port}"
        report.meta.api_base_url = baseUrl
        report.meta.csv_path = csvPath
        report.meta.plan_path = planPath or plan.meta.plan_path
        report.meta.include_deleted_users = include_deleted
        report.meta.stop_on_first_error = stop_on_first_error
        report.meta.max_actions = max_actions
        report.meta.dry_run = dry_run
        report.meta.resource_exists_retries = resource_exists_retries
        report.meta.retries = settings.retries
        report.meta.retry_backoff_seconds = settings.retry_backoff_seconds
        report.meta.report_items_limit = report_items_limit
        report.meta.report_items_success = report_items_success

        report.summary.planned_create = plan.summary.planned_create
        report.summary.planned_update = plan.summary.planned_update
        report.summary.skipped = plan.summary.skipped
        report.summary.failed = plan.summary.failed

        user_api = createUserApiClient(settings)
        service = ImportApplyService(user_api)
        exit_code = service.applyPlan(
            plan=plan,
            logger=logger,
            report=report,
            run_id=runId,
            stop_on_first_error=stop_on_first_error,
            max_actions=max_actions,
            dry_run=dry_run,
            report_items_limit=report_items_limit,
            report_items_success=report_items_success,
            resource_exists_retries=resource_exists_retries,
        )
        if hasattr(user_api, "client"):
            report.meta.retries_used = getattr(user_api.client, "getRetryAttempts", lambda: None)()
        return exit_code

    runWithReport(
        ctx=ctx,
        commandName="import-apply",
        csvPath=csvPath,
        requiresCsv=False,
        requiresApiAccess=True,
        runner=execute,
    )
def runCheckApiCommand(ctx: typer.Context, apiTransport=None) -> None:
    settings: Settings = ctx.obj["settings"]
    runId = ctx.obj["runId"]

    def execute(logger, report) -> int:
        baseUrl = f"https://{settings.host}:{settings.port}"
        client = AnkeyApiClient(
            baseUrl=baseUrl,
            username=settings.api_username or "",
            password=settings.api_password or "",
            timeoutSeconds=settings.timeout_seconds,
            tlsSkipVerify=settings.tls_skip_verify,
            caFile=settings.ca_file,
            retries=settings.retries,
            retryBackoffSeconds=settings.retry_backoff_seconds,
            transport=apiTransport,
        )
        try:
            start = time.monotonic()
            client.getJson("/ankey/managed/user", {"page": 1, "rows": 1, "_queryFilter": "true"})
            latency_ms = int((time.monotonic() - start) * 1000)
            logEvent(logger, logging.INFO, runId, "api", f"api ok base_url={baseUrl} latency_ms={latency_ms}")
            report.meta.api_base_url = baseUrl
            return 0
        except ApiError as exc:
            logEvent(logger, logging.ERROR, runId, "api", f"API check failed: {exc}")
            typer.echo("ERROR: API check failed (see logs/report)", err=True)
            return 2

    runWithReport(
        ctx=ctx,
        commandName="check-api",
        csvPath=None,
        requiresCsv=False,
        requiresApiAccess=True,
        runner=execute,
    )

def runValidateCommand(ctx: typer.Context, csvPath: str | None, csvHasHeader: bool | None) -> None:
    runId = ctx.obj["runId"]
    settings: Settings = ctx.obj["settings"]
    csv_has_header = csvHasHeader if csvHasHeader is not None else settings.csv_has_header

    def execute(logger, report) -> int:
        rows_processed = 0
        failed_rows = 0
        warning_rows = 0
        matchkey_seen: dict[str, int] = {}
        usr_org_tab_seen: dict[str, int] = {}
        ctx_validation = ValidationContext(
            matchkey_seen=matchkey_seen, usr_org_tab_seen=usr_org_tab_seen, org_lookup=None, on_missing_org="error"
        )

        try:
            for csvRow in readEmployeeRows(csvPath, hasHeader=csv_has_header):
                _employee, result = validateEmployeeRowWithContext(csvRow, ctx_validation)
                rows_processed += 1

                status = "valid" if result.valid else "invalid"
                if not result.valid:
                    failed_rows += 1
                if result.warnings:
                    warning_rows += 1

                item_index = len(report.items)
                report.items.append(
                    {
                        "row_id": f"line:{result.line_no}",
                        "line_no": result.line_no,
                        "match_key": result.match_key,
                        "status": status,
                        "errors": [
                            {"code": e.code, "field": e.field, "message": e.message} for e in result.errors
                        ],
                        "warnings": [
                            {"code": w.code, "field": w.field, "message": w.message} for w in result.warnings
                        ],
                    }
                )
                if not result.valid:
                    logValidationFailure(
                        logger,
                        runId,
                        "validate",
                        result,
                        item_index,
                        errors=result.errors,
                        warnings=result.warnings,
                    )
        except CsvFormatError as exc:
            logEvent(logger, logging.ERROR, runId, "csv", f"CSV format error: {exc}")
            typer.echo(f"ERROR: CSV format error: {exc}", err=True)
            return 2
        except OSError as exc:
            logEvent(logger, logging.ERROR, runId, "csv", f"CSV read error: {exc}")
            typer.echo(f"ERROR: CSV read error: {exc}", err=True)
            return 2

        report.meta.csv_rows_total = rows_processed
        report.meta.csv_rows_processed = rows_processed
        report.summary.failed = failed_rows
        report.summary.warnings = warning_rows
        report.summary.skipped = 0
        logEvent(
            logger,
            logging.INFO,
            runId,
            "validate",
            f"validate done rows_total={rows_processed} invalid={failed_rows} warnings={warning_rows}",
        )

        return 1 if failed_rows > 0 else 0

    runWithReport(
        ctx=ctx,
        commandName="validate",
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
        runId = str(uuid.uuid4())

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

@importApp.command("plan")
def importPlan(
    ctx: typer.Context,
    csv: str | None = typer.Option(None, "--csv", help="Path to input CSV"),
    csvHasHeader: bool | None = typer.Option(None, "--csv-has-header", help="CSV includes header row"),
    includeDeletedUsers: bool | None = typer.Option(
        None,
        "--include-deleted-users/--no-include-deleted-users",
        help="Include deleted users in matching",
        show_default=True,
    ),
    onMissingOrg: str | None = typer.Option(
        None,
        "--on-missing-org",
        help="Policy when organization_id missing in cache: error|warn-and-skip",
        case_sensitive=False,
    ),
    reportItemsLimit: int | None = typer.Option(None, "--report-items-limit", help="Limit report items stored"),
    reportItemsSuccess: bool | None = typer.Option(
        None,
        "--report-items-success/--no-report-items-success",
        help="Include successful items in report",
        show_default=True,
    ),
):
    runImportPlanCommand(
        ctx=ctx,
        csvPath=csv,
        csvHasHeader=csvHasHeader,
        includeDeletedUsers=includeDeletedUsers,
        onMissingOrg=onMissingOrg.lower() if onMissingOrg else None,
        reportItemsLimit=reportItemsLimit,
        reportItemsSuccess=reportItemsSuccess,
    )


@importApp.command("apply")
def importApply(
    ctx: typer.Context,
    csv: str | None = typer.Option(None, "--csv", help="Path to input CSV"),
    plan: str | None = typer.Option(None, "--plan", help="Path to plan_import.json"),
    csvHasHeader: bool | None = typer.Option(None, "--csv-has-header", help="CSV includes header row"),
    stopOnFirstError: bool | None = typer.Option(
        None,
        "--stop-on-first-error/--no-stop-on-first-error",
        help="Stop on first failed apply",
        show_default=True,
    ),
    maxActions: int | None = typer.Option(None, "--max-actions", help="Limit number of actions to apply"),
    dryRun: bool | None = typer.Option(None, "--dry-run/--no-dry-run", help="Do not send API requests"),
    includeDeletedUsers: bool | None = typer.Option(
        None,
        "--include-deleted-users/--no-include-deleted-users",
        help="Include deleted users in matching when building plan from CSV",
        show_default=True,
    ),
    onMissingOrg: str | None = typer.Option(
        None,
        "--on-missing-org",
        help="Policy when organization_id missing in cache: error|warn-and-skip",
        case_sensitive=False,
    ),
    resourceExistsRetries: int | None = typer.Option(
        None,
        "--resource-exists-retries",
        help="Retries for resourceExists on create",
    ),
    reportItemsLimit: int | None = typer.Option(None, "--report-items-limit", help="Limit report items stored"),
    reportItemsSuccess: bool | None = typer.Option(
        None,
        "--report-items-success/--no-report-items-success",
        help="Include successful items in report",
        show_default=True,
    ),
):
    runImportApplyCommand(
        ctx=ctx,
        csvPath=csv,
        planPath=plan,
        csvHasHeader=csvHasHeader,
        stopOnFirstError=stopOnFirstError,
        maxActions=maxActions,
        dryRun=dryRun,
        includeDeletedUsers=includeDeletedUsers,
        onMissingOrg=onMissingOrg.lower() if onMissingOrg else None,
        reportItemsLimit=reportItemsLimit,
        reportItemsSuccess=reportItemsSuccess,
        resourceExistsRetries=resourceExistsRetries,
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
    includeDeletedUsers: bool | None = typer.Option(
        None,
        "--include-deleted-users/--no-include-deleted-users",
        help="Include users with accountStatus=deleted or deletionDate set",
        show_default=True,
    ),
    reportItemsLimit: int | None = typer.Option(None, "--report-items-limit", help="Limit report items stored"),
    reportItemsSuccess: bool | None = typer.Option(
        None,
        "--report-items-success/--no-report-items-success",
        help="Include successful items in report",
        show_default=True,
    ),
):
    runCacheRefreshCommand(
        ctx=ctx,
        pageSize=pageSize if pageSize is not None else ctx.obj["settings"].page_size,
        maxPages=maxPages if maxPages is not None else ctx.obj["settings"].max_pages,
        timeoutSeconds=timeoutSeconds if timeoutSeconds is not None else ctx.obj["settings"].timeout_seconds,
        retries=retries if retries is not None else ctx.obj["settings"].retries,
        retryBackoffSeconds=retryBackoffSeconds if retryBackoffSeconds is not None else ctx.obj["settings"].retry_backoff_seconds,
        includeDeletedUsers=includeDeletedUsers if includeDeletedUsers is not None else ctx.obj["settings"].include_deleted_users,
        reportItemsLimit=reportItemsLimit if reportItemsLimit is not None else ctx.obj["settings"].report_items_limit,
        reportItemsSuccess=reportItemsSuccess if reportItemsSuccess is not None else ctx.obj["settings"].report_items_success,
    )

@cacheApp.command("status")
def cacheStatus(ctx: typer.Context):
    runCacheStatusCommand(ctx)

@cacheApp.command("clear")
def cacheClear(ctx: typer.Context):
    runCacheClearCommand(ctx)

app.add_typer(cacheApp, name="cache")
app.add_typer(importApp, name="import")
app.add_typer(userApp, name="user")
