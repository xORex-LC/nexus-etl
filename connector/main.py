from __future__ import annotations

import logging
import sqlite3
import sys
import time
from pathlib import Path

import typer

from connector.infra.http.ankey_client import AnkeyApiClient, ApiError
from connector.infra.http.request_executor import AnkeyRequestExecutor
from connector.infra.cache.db import getCacheDbPath, openCacheDb
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.cache.repository import SqliteCacheRepository
from connector.infra.cache.handlers.registry import CacheHandlerRegistry
from connector.infra.cache.handlers.employees_handler import EmployeesCacheHandler
from connector.infra.cache.handlers.organizations_handler import OrganizationsCacheHandler
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.target.ankey_gateway import AnkeyTargetPagedReader
from connector.usecases.cache_command_service import CacheCommandService
from connector.usecases.cache_refresh_service import CacheRefreshUseCase
from connector.usecases.cache_clear_usecase import CacheClearUseCase
from connector.config.config import Settings, loadSettings
from connector.infra.sources.csv_utils import CsvFormatError
from connector.infra.logging.setup import StdStreamToLogger, TeeStream, createCommandLogger, logEvent
from connector.usecases.import_apply_service import ImportApplyService
from connector.usecases.import_plan_service import ImportPlanService
from connector.usecases.enrich_usecase import EnrichUseCase
from connector.usecases.mapping_usecase import MappingUseCase
from connector.usecases.normalize_usecase import NormalizeUseCase
from connector.usecases.validate_usecase import ValidateUseCase
from connector.infra.artifacts.plan_reader import readPlanFile
from connector.usecases.ports import CacheCommandServiceProtocol, ImportPlanServiceProtocol
from connector.infra.artifacts.report_writer import createEmptyReport, finalizeReport, writeReportJson
from connector.common.sanitize import maskSecret
from connector.common.time import getDurationMs
from connector.common.run_id import generate_run_id
from connector.domain.validation.pipeline import logValidationFailure
from connector.domain.validation.deps import ValidationDependencies
from connector.datasets.registry import get_spec
from connector.datasets.cache_registry import list_cache_sync_adapters
from connector.infra.secrets import (
    NullSecretProvider,
    PromptSecretProvider,
    CompositeSecretProvider,
    FileVaultSecretStore,
)
from connector.domain.ports.secrets import SecretProviderProtocol

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
    includeDeleted: bool | None = None,
    reportItemsLimit: int | None = None,
    dataset: str | None = None,
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
        try:
            conn = openCacheDb(cacheDbPath)
        except sqlite3.Error as exc:
            logEvent(logger, logging.ERROR, runId, "cache", f"Failed to open cache DB: {exc}")
            typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
            return 2

        try:
            base_url = f"https://{settings.host}:{settings.port}"
            client = AnkeyApiClient(
                baseUrl=base_url,
                username=settings.api_username or "",
                password=settings.api_password or "",
                timeoutSeconds=timeoutSeconds or settings.timeout_seconds,
                tlsSkipVerify=settings.tls_skip_verify,
                caFile=settings.ca_file,
                retries=retries or settings.retries,
                retryBackoffSeconds=retryBackoffSeconds or settings.retry_backoff_seconds,
                transport=apiTransport,
            )
            client.resetRetryAttempts()

            engine = SqliteEngine(conn)
            handler_registry = CacheHandlerRegistry()
            handler_registry.register(EmployeesCacheHandler())
            handler_registry.register(OrganizationsCacheHandler())
            ensure_cache_ready(engine, handler_registry)

            cache_repo = SqliteCacheRepository(engine, handler_registry)
            if dataset is not None and dataset not in cache_repo.list_datasets():
                typer.echo(f"ERROR: Unsupported cache dataset: {dataset}", err=True)
                return 2
            reader = AnkeyTargetPagedReader(client)
            adapters = list_cache_sync_adapters()
            cache_refresh = CacheRefreshUseCase(reader, cache_repo, adapters)
            service: CacheCommandServiceProtocol = CacheCommandService(cache_repo, cache_refresh)

            return service.refresh(
                page_size=pageSize or settings.page_size,
                max_pages=maxPages or settings.max_pages,
                logger=logger,
                report=report,
                run_id=runId,
                include_deleted=includeDeleted if includeDeleted is not None else settings.include_deleted,
                report_items_limit=reportItemsLimit or settings.report_items_limit,
                api_base_url=base_url,
                retries=retries or settings.retries,
                retry_backoff_seconds=retryBackoffSeconds or settings.retry_backoff_seconds,
                dataset=dataset,
            )
        except ValueError as exc:
            typer.echo(f"ERROR: {exc}", err=True)
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

def runCacheStatusCommand(ctx: typer.Context, dataset: str | None = None) -> None:
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
            engine = SqliteEngine(conn)
            handler_registry = CacheHandlerRegistry()
            handler_registry.register(EmployeesCacheHandler())
            handler_registry.register(OrganizationsCacheHandler())
            ensure_cache_ready(engine, handler_registry)

            cache_repo = SqliteCacheRepository(engine, handler_registry)
            if dataset is not None and dataset not in cache_repo.list_datasets():
                typer.echo(f"ERROR: Unsupported cache dataset: {dataset}", err=True)
                return 2
            service: CacheCommandServiceProtocol = CacheCommandService(cache_repo)
            code, status = service.status(logger, report, runId, dataset=dataset)
            if code != 0:
                typer.echo("ERROR: cache status failed (see logs/report)", err=True)
                return code
            if "by_dataset" in status:
                schema_version = status.get("schema_version")
                total = status.get("total")
                typer.echo(f"schema_version={schema_version} total={total}")
                for name, info in status["by_dataset"].items():
                    typer.echo(f"{name}: count={info.get('count')} meta={info.get('meta')}")
            else:
                typer.echo(
                    "schema_version={schema_version} dataset={dataset} counts={counts} meta={meta}".format(
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

def runCacheClearCommand(ctx: typer.Context, dataset: str | None = None) -> None:
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
            engine = SqliteEngine(conn)
            handler_registry = CacheHandlerRegistry()
            handler_registry.register(EmployeesCacheHandler())
            handler_registry.register(OrganizationsCacheHandler())
            ensure_cache_ready(engine, handler_registry)

            cache_repo = SqliteCacheRepository(engine, handler_registry)
            if dataset is not None and dataset not in cache_repo.list_datasets():
                typer.echo(f"ERROR: Unsupported cache dataset: {dataset}", err=True)
                return 2
            cache_clear = CacheClearUseCase(cache_repo)
            service: CacheCommandServiceProtocol = CacheCommandService(cache_repo, cache_clear=cache_clear)
            code, _cleared = service.clear(logger, report, runId, dataset=dataset)
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
    includeDeleted: bool | None,
    reportItemsLimit: int | None,
    reportIncludeSkipped: bool | None,
    dataset: str | None,
    vaultFile: str | None,
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

        include_deleted = includeDeleted if includeDeleted is not None else settings.include_deleted
        report_items_limit = reportItemsLimit if reportItemsLimit is not None else settings.report_items_limit
        report_include_skipped = (
            reportIncludeSkipped if reportIncludeSkipped is not None else settings.report_include_skipped
        )
        dataset_name = dataset if dataset is not None else settings.dataset_name
        csv_has_header = csvHasHeader if csvHasHeader is not None else settings.csv_has_header
        report.meta.report_items_limit = report_items_limit
        report.meta.report_include_skipped = report_include_skipped
        report.meta.dataset = dataset_name

        try:
            engine = SqliteEngine(conn)
            handler_registry = CacheHandlerRegistry()
            handler_registry.register(EmployeesCacheHandler())
            handler_registry.register(OrganizationsCacheHandler())
            ensure_cache_ready(engine, handler_registry)

            service: ImportPlanServiceProtocol = ImportPlanService()
            return service.run(
                conn=conn,
                csv_path=csvPath or "",
                csv_has_header=csv_has_header,
                include_deleted=include_deleted,
                settings=settings,
                dataset=dataset_name,
                logger=logger,
                run_id=runId,
                report=report,
                report_items_limit=report_items_limit,
                include_skipped_in_report=report_include_skipped,
                report_dir=settings.report_dir,
                vault_file=vaultFile,
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
    planPath: str | None,
    stopOnFirstError: bool | None,
    maxActions: int | None,
    dryRun: bool | None,
    reportItemsLimit: int | None,
    resourceExistsRetries: int | None,
    secretsFrom: str | None,
    vaultFile: str | None,
) -> None:
    settings: Settings = ctx.obj["settings"]
    runId = ctx.obj["runId"]
    cacheDbPath = getCacheDbPath(settings.cache_dir)

    def execute(logger, report) -> int:
        if not planPath:
            typer.echo("ERROR: --plan is required (apply no longer builds plan from CSV)", err=True)
            return 2

        report_items_limit = reportItemsLimit if reportItemsLimit is not None else settings.report_items_limit
        resource_exists_retries = (
            resourceExistsRetries if resourceExistsRetries is not None else settings.resource_exists_retries
        )
        stop_on_first_error = (
            stopOnFirstError if stopOnFirstError is not None else settings.stop_on_first_error
        )
        max_actions = maxActions if maxActions is not None else settings.max_actions
        dry_run = dryRun if dryRun is not None else settings.dry_run

        try:
            plan = readPlanFile(planPath or "")
        except (OSError, ValueError) as exc:
            logEvent(logger, logging.ERROR, runId, "plan", f"Import apply failed: {exc}")
            typer.echo(f"ERROR: import apply failed: {exc}", err=True)
            return 2

        dataset_name = plan.meta.dataset

        baseUrl = f"https://{settings.host}:{settings.port}"
        report.meta.api_base_url = baseUrl
        report.meta.csv_path = None
        report.meta.plan_path = planPath or plan.meta.plan_path
        report.meta.include_deleted = plan.meta.include_deleted
        report.meta.dataset = dataset_name
        report.meta.stop_on_first_error = stop_on_first_error
        report.meta.max_actions = max_actions
        report.meta.dry_run = dry_run
        report.meta.resource_exists_retries = resource_exists_retries
        report.meta.retries = settings.retries
        report.meta.retry_backoff_seconds = settings.retry_backoff_seconds
        report.meta.report_items_limit = report_items_limit

        report.summary.planned_create = plan.summary.planned_create if plan.summary else 0
        report.summary.planned_update = plan.summary.planned_update if plan.summary else 0
        report.summary.skipped = plan.summary.skipped if plan.summary else 0
        report.summary.failed = plan.summary.failed_rows if plan.summary else 0

        client = AnkeyApiClient(
            baseUrl=f"https://{settings.host}:{settings.port}",
            username=settings.api_username or "",
            password=settings.api_password or "",
            timeoutSeconds=settings.timeout_seconds,
            tlsSkipVerify=settings.tls_skip_verify,
            caFile=settings.ca_file,
            retries=settings.retries,
            retryBackoffSeconds=settings.retry_backoff_seconds,
        )
        client.resetRetryAttempts()
        secrets_provider = build_secret_provider(secretsFrom, vaultFile)
        executor = AnkeyRequestExecutor(client)
        service = ImportApplyService(executor, secrets=secrets_provider, spec_resolver=get_spec)
        exit_code = service.applyPlan(
            plan=plan,
            logger=logger,
            report=report,
            run_id=runId,
            stop_on_first_error=stop_on_first_error,
            max_actions=max_actions,
            dry_run=dry_run,
            report_items_limit=report_items_limit,
            resource_exists_retries=resource_exists_retries,
        )
        if hasattr(client, "getRetryAttempts"):
            report.meta.retries_used = client.getRetryAttempts()
        return exit_code

    runWithReport(
        ctx=ctx,
        commandName="import-apply",
        csvPath=None,
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
    dataset_name = settings.dataset_name

    def execute(logger, report) -> int:
        deps = ValidationDependencies()
        dataset_spec = get_spec(dataset_name)
        try:
            conn = openCacheDb(getCacheDbPath(settings.cache_dir))
        except sqlite3.Error as exc:
            logEvent(logger, logging.ERROR, runId, "cache", f"Failed to open cache DB: {exc}")
            typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
            return 2
        try:
            engine = SqliteEngine(conn)
            handler_registry = CacheHandlerRegistry()
            handler_registry.register(EmployeesCacheHandler())
            handler_registry.register(OrganizationsCacheHandler())
            ensure_cache_ready(engine, handler_registry)

            enrich_deps = dataset_spec.build_enrich_deps(conn, settings, secret_store=None)
            validators = dataset_spec.build_validators(deps, enrich_deps)
            row_validator = validators.row_validator
            dataset_validator = validators.dataset_validator
            report_items_limit = settings.report_items_limit
            report.meta.report_items_limit = report_items_limit
            report.meta.dataset = dataset_name
            record_source = dataset_spec.build_record_source(
                csv_path=csvPath,
                csv_has_header=csv_has_header,
            )

            try:
                enrich_usecase = EnrichUseCase(
                    report_items_limit=report_items_limit,
                    include_enriched_items=False,
                )
                enriched_ok = enrich_usecase.iter_enriched_ok(
                    record_source=record_source,
                    row_validator=row_validator,
                )
                validate_usecase = ValidateUseCase(
                    report_items_limit=report_items_limit,
                    include_valid_items=False,
                )
                return validate_usecase.run(
                    enriched_source=enriched_ok,
                    row_validator=row_validator,
                    dataset_validator=dataset_validator,
                    dataset=dataset_name,
                    logger=logger,
                    run_id=runId,
                    report=report,
                    log_failure=logValidationFailure,
                )
            except CsvFormatError as exc:
                logEvent(logger, logging.ERROR, runId, "csv", f"CSV format error: {exc}")
                typer.echo(f"ERROR: CSV format error: {exc}", err=True)
                return 2
            except OSError as exc:
                logEvent(logger, logging.ERROR, runId, "csv", f"CSV read error: {exc}")
                typer.echo(f"ERROR: CSV read error: {exc}", err=True)
                return 2
        finally:
            conn.close()

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
    runId = ctx.obj["runId"]
    settings: Settings = ctx.obj["settings"]
    csv_has_header = csvHasHeader if csvHasHeader is not None else settings.csv_has_header
    dataset_name = dataset if dataset is not None else settings.dataset_name
    report_items_limit = reportItemsLimit if reportItemsLimit is not None else settings.report_items_limit
    include_mapped_items = includeMappedItems if includeMappedItems is not None else True

    def execute(logger, report) -> int:
        deps = ValidationDependencies()
        dataset_spec = get_spec(dataset_name)
        report.meta.report_items_limit = report_items_limit
        report.meta.dataset = dataset_name

        try:
            conn = openCacheDb(getCacheDbPath(settings.cache_dir))
        except sqlite3.Error as exc:
            logEvent(logger, logging.ERROR, runId, "cache", f"Failed to open cache DB: {exc}")
            typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
            return 2
        try:
            engine = SqliteEngine(conn)
            handler_registry = CacheHandlerRegistry()
            handler_registry.register(EmployeesCacheHandler())
            handler_registry.register(OrganizationsCacheHandler())
            ensure_cache_ready(engine, handler_registry)

            enrich_deps = dataset_spec.build_enrich_deps(conn, settings, secret_store=None)
            validators = dataset_spec.build_validators(deps, enrich_deps)
            row_validator = validators.row_validator

            record_source = dataset_spec.build_record_source(
                csv_path=csvPath,
                csv_has_header=csv_has_header,
            )
            usecase = MappingUseCase(
                report_items_limit=report_items_limit,
                include_mapped_items=include_mapped_items,
            )
            return usecase.run(
                record_source=record_source,
                row_validator=row_validator,
                dataset=dataset_name,
                logger=logger,
                run_id=runId,
                report=report,
            )
        except CsvFormatError as exc:
            logEvent(logger, logging.ERROR, runId, "csv", f"CSV format error: {exc}")
            typer.echo(f"ERROR: CSV format error: {exc}", err=True)
            return 2
        except OSError as exc:
            logEvent(logger, logging.ERROR, runId, "csv", f"CSV read error: {exc}")
            typer.echo(f"ERROR: CSV read error: {exc}", err=True)
            return 2
        finally:
            conn.close()

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
    runId = ctx.obj["runId"]
    settings: Settings = ctx.obj["settings"]
    csv_has_header = csvHasHeader if csvHasHeader is not None else settings.csv_has_header
    dataset_name = dataset if dataset is not None else settings.dataset_name
    report_items_limit = reportItemsLimit if reportItemsLimit is not None else settings.report_items_limit
    include_normalized_items = includeNormalizedItems if includeNormalizedItems is not None else True

    def execute(logger, report) -> int:
        deps = ValidationDependencies()
        dataset_spec = get_spec(dataset_name)
        report.meta.report_items_limit = report_items_limit
        report.meta.dataset = dataset_name

        try:
            conn = openCacheDb(getCacheDbPath(settings.cache_dir))
        except sqlite3.Error as exc:
            logEvent(logger, logging.ERROR, runId, "cache", f"Failed to open cache DB: {exc}")
            typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
            return 2
        try:
            engine = SqliteEngine(conn)
            handler_registry = CacheHandlerRegistry()
            handler_registry.register(EmployeesCacheHandler())
            handler_registry.register(OrganizationsCacheHandler())
            ensure_cache_ready(engine, handler_registry)

            enrich_deps = dataset_spec.build_enrich_deps(conn, settings, secret_store=None)
            validators = dataset_spec.build_validators(deps, enrich_deps)
            row_validator = validators.row_validator

            record_source = dataset_spec.build_record_source(
                csv_path=csvPath,
                csv_has_header=csv_has_header,
            )
            usecase = NormalizeUseCase(
                report_items_limit=report_items_limit,
                include_normalized_items=include_normalized_items,
            )
            return usecase.run(
                record_source=record_source,
                row_validator=row_validator,
                dataset=dataset_name,
                logger=logger,
                run_id=runId,
                report=report,
            )
        except CsvFormatError as exc:
            logEvent(logger, logging.ERROR, runId, "csv", f"CSV format error: {exc}")
            typer.echo(f"ERROR: CSV format error: {exc}", err=True)
            return 2
        except OSError as exc:
            logEvent(logger, logging.ERROR, runId, "csv", f"CSV read error: {exc}")
            typer.echo(f"ERROR: CSV read error: {exc}", err=True)
            return 2
        finally:
            conn.close()

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
    runId = ctx.obj["runId"]
    settings: Settings = ctx.obj["settings"]
    csv_has_header = csvHasHeader if csvHasHeader is not None else settings.csv_has_header
    dataset_name = dataset if dataset is not None else settings.dataset_name
    report_items_limit = reportItemsLimit if reportItemsLimit is not None else settings.report_items_limit
    include_enriched_items = includeEnrichedItems if includeEnrichedItems is not None else True

    def execute(logger, report) -> int:
        deps = ValidationDependencies()
        dataset_spec = get_spec(dataset_name)
        report.meta.report_items_limit = report_items_limit
        report.meta.dataset = dataset_name

        try:
            conn = openCacheDb(getCacheDbPath(settings.cache_dir))
        except sqlite3.Error as exc:
            logEvent(logger, logging.ERROR, runId, "cache", f"Failed to open cache DB: {exc}")
            typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
            return 2
        try:
            engine = SqliteEngine(conn)
            handler_registry = CacheHandlerRegistry()
            handler_registry.register(EmployeesCacheHandler())
            handler_registry.register(OrganizationsCacheHandler())
            ensure_cache_ready(engine, handler_registry)

            secret_store = FileVaultSecretStore(vaultFile) if vaultFile else None
            enrich_deps = dataset_spec.build_enrich_deps(conn, settings, secret_store=secret_store)
            validators = dataset_spec.build_validators(deps, enrich_deps)
            row_validator = validators.row_validator

            record_source = dataset_spec.build_record_source(
                csv_path=csvPath,
                csv_has_header=csv_has_header,
            )
            usecase = EnrichUseCase(
                report_items_limit=report_items_limit,
                include_enriched_items=include_enriched_items,
            )
            return usecase.run(
                record_source=record_source,
                row_validator=row_validator,
                dataset=dataset_name,
                logger=logger,
                run_id=runId,
                report=report,
            )
        except CsvFormatError as exc:
            logEvent(logger, logging.ERROR, runId, "csv", f"CSV format error: {exc}")
            typer.echo(f"ERROR: CSV format error: {exc}", err=True)
            return 2
        except OSError as exc:
            logEvent(logger, logging.ERROR, runId, "csv", f"CSV read error: {exc}")
            typer.echo(f"ERROR: CSV read error: {exc}", err=True)
            return 2
        finally:
            conn.close()

    runWithReport(
        ctx=ctx,
        commandName="enrich",
        csvPath=csvPath,
        requiresCsv=True,
        requiresApiAccess=False,
        runner=execute,
    )


def build_secret_provider(source: str | None, vault_file: str | None) -> SecretProviderProtocol:
    """
    Назначение:
        Фабрика провайдера секретов для apply.
    Контракт:
        - source None/\"none\" -> NullSecretProvider
        - source \"prompt\" -> PromptSecretProvider
        - source \"vault\" -> CompositeSecretProvider(FileVault -> Prompt)
        - любое другое значение: NullSecretProvider (по умолчанию)
    """
    if not source or source == "none":
        return NullSecretProvider()
    if source == "prompt":
        return PromptSecretProvider()
    if source == "vault":
        if not vault_file:
            return PromptSecretProvider()
        from connector.infra.secrets import FileVaultSecretProvider

        return CompositeSecretProvider([FileVaultSecretProvider(vault_file), PromptSecretProvider()])
    return NullSecretProvider()

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
