from __future__ import annotations

import uuid
from pathlib import Path
import typer

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
    )


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
    """
    Назначение:
        Команда validate (этап 1 — заглушка).
        По ТЗ: проверяет CSV без API и формирует отчёт.

    Входные данные:
        --csv: путь к CSV

    Выходные данные:
        На этапе 1 — только проверка наличия CSV + вывод заглушки.
    """
    requireCsv(csv)
    runId = ctx.obj["runId"]
    settings: Settings = ctx.obj["settings"]
    sources = ctx.obj["sources"]
    printRunHeader(runId, "validate", settings, sources)
    typer.echo("validate: not implemented yet (stage 1)")


@app.command("import")
def importEmployees(ctx: typer.Context, csv: str | None = typer.Option(None, "--csv", help="Path to input CSV")):
    """
    Назначение:
        Команда import (этап 1 — заглушка).
        По ТЗ: импорт/обновление сотрудников из CSV через REST API.

    Входные данные:
        --csv: путь к CSV

    Выходные данные:
        На этапе 1 — только проверка наличия CSV + вывод заглушки.
    """
    requireCsv(csv)
    runId = ctx.obj["runId"]
    settings: Settings = ctx.obj["settings"]
    sources = ctx.obj["sources"]
    printRunHeader(runId, "import", settings, sources)
    typer.echo("import: not implemented yet (stage 1)")


@app.command("check-api")
def checkApi(ctx: typer.Context):
    """
    Назначение:
        Команда check-api (этап 1 — заглушка).
        По ТЗ: проверка доступности API и корректности учётных данных.

    Входные данные:
        Использует настройки API из конфигов/ENV/CLI.

    Выходные данные:
        На этапе 1 — только проверка, что настройки API заданы.
    """
    runId = ctx.obj["runId"]
    settings: Settings = ctx.obj["settings"]
    sources = ctx.obj["sources"]
    requireApi(settings)
    printRunHeader(runId, "check-api", settings, sources)
    typer.echo("check-api: not implemented yet (stage 1)")


@cacheApp.command("refresh")
def cacheRefresh(ctx: typer.Context):
    """
    Назначение:
        Команда cache refresh (этап 1 — заглушка).
        По ТЗ: обновляет локальный кэш (в будущем SQLite) из API.

    Входные данные:
        Использует настройки API из конфигов/ENV/CLI.

    Выходные данные:
        На этапе 1 — только проверка, что настройки API заданы.
    """
    runId = ctx.obj["runId"]
    settings: Settings = ctx.obj["settings"]
    sources = ctx.obj["sources"]
    requireApi(settings)
    printRunHeader(runId, "cache refresh", settings, sources)
    typer.echo("cache refresh: not implemented yet (stage 1)")


app.add_typer(cacheApp, name="cache")
app.add_typer(userApp, name="user")