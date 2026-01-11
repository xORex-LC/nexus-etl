from __future__ import annotations

import uuid
from pathlib import Path
import typer
import logging
import sys
import time

from .loggingSetup import createCommandLogger, logEvent, StdStreamToLogger, TeeStream
from .reporter import createEmptyReport, finalizeReport, writeReportJson
from .timeUtils import getDurationMs

from .config import loadSettings, Settings
from .sanitize import maskSecret

app = typer.Typer(no_args_is_help=True, add_completion=False)
cacheApp = typer.Typer(no_args_is_help=True)
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
        f"log_level={settings.log_level} log_json={settings.log_json} "
    )

def runCommand(
    ctx: typer.Context,
    commandName: str,
    csvPath: str | None,
    requiresCsv: bool,
    requiresApiAccess: bool,
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

        # На этапе 2 команды ещё заглушки
        typer.echo(f"{commandName}: not implemented yet (stage 2)")

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

@app.callback()
def main(
    ctx: typer.Context,
    config: str | None = typer.Option(None, "--config", help="Path to config.yml"),
    runId: str | None = typer.Option(None, "--run-id", help="Run identifier (UUID). If omitted, generated."),
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
    logLevel: str | None = typer.Option(None, "--log-level", help="Log level: ERROR|WARN|INFO|DEBUG"),
    logJson: bool | None = typer.Option(None, "--log-json", help="Enable JSON log format (reserved)"),
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
        "log_dir": logDir,
        "report_dir": reportDir,
        "cache_dir": cacheDir,
        "tls_skip_verify": tlsSkipVerify,
        "ca_file": caFile,
        "log_level": logLevel,
        "log_json": logJson,
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
def validate(ctx: typer.Context, csv: str | None = typer.Option(None, "--csv", help="Path to input CSV")):
    runCommand(ctx, "validate", csv, requiresCsv=True, requiresApiAccess=False)

@app.command("import")
def importEmployees(ctx: typer.Context, csv: str | None = typer.Option(None, "--csv", help="Path to input CSV")):
    runCommand(ctx, "import", csv, requiresCsv=True, requiresApiAccess=True)

@app.command("check-api")
def checkApi(ctx: typer.Context):
    runCommand(ctx, "check-api", None, requiresCsv=False, requiresApiAccess=True)

@cacheApp.command("refresh")
def cacheRefresh(ctx: typer.Context):
    runCommand(ctx, "cache-refresh", None, requiresCsv=False, requiresApiAccess=True)

app.add_typer(cacheApp, name="cache")
app.add_typer(userApp, name="user")