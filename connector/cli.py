from __future__ import annotations

import uuid
from pathlib import Path
import typer

from .config import load_settings, Settings
from .sanitize import mask_secret

app = typer.Typer(no_args_is_help=True, add_completion=False)
cache_app = typer.Typer(no_args_is_help=True)
user_app = typer.Typer(no_args_is_help=True)  # зарезервировано на будущее (ТЗ допускает)


def _ensure_dir(path: str) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


def _require_csv(csv_path: str | None) -> None:
    if not csv_path:
        typer.echo("ERROR: --csv is required", err=True)
        raise typer.Exit(code=2)
    p = Path(csv_path)
    if not p.exists() or not p.is_file():
        typer.echo(f"ERROR: CSV file not found: {csv_path}", err=True)
        raise typer.Exit(code=2)


def _require_api(s: Settings) -> None:
    missing = []
    if not s.host:
        missing.append("host")
    if not s.port:
        missing.append("port")
    if not s.api_username:
        missing.append("api_username")
    if not s.api_password:
        missing.append("api_password")
    if missing:
        typer.echo(f"ERROR: missing API settings: {', '.join(missing)}", err=True)
        raise typer.Exit(code=2)


def _print_run_header(run_id: str, cmd: str, settings: Settings, sources: list[str]) -> None:
    typer.echo(
        f"run_id={run_id} command={cmd} "
        f"host={settings.host} port={settings.port} api_username={settings.api_username} "
        f"api_password={mask_secret(settings.api_password)} "
        f"sources={sources}"
    )


@app.callback()
def main(
    ctx: typer.Context,
    config: str | None = typer.Option(None, "--config", help="Path to config.yml"),
    run_id: str | None = typer.Option(None, "--run-id", help="Run identifier (UUID). If omitted, generated."),
    log_dir: str | None = typer.Option(None, "--log-dir", help="Directory for logs."),
    report_dir: str | None = typer.Option(None, "--report-dir", help="Directory for reports."),
    cache_dir: str | None = typer.Option(None, "--cache-dir", help="Directory for cache (SQLite later)."),
    # API overrides
    host: str | None = typer.Option(None, "--host", help="API host/IP"),
    port: int | None = typer.Option(None, "--port", help="API port"),
    api_username: str | None = typer.Option(None, "--api-username", help="API username"),
    api_password: str | None = typer.Option(None, "--api-password", help="API password (avoid; use env/file)"),
    api_password_file: str | None = typer.Option(None, "--api-password-file", help="Read API password from file"),
    # TLS
    tls_skip_verify: bool | None = typer.Option(None, "--tls-skip-verify", help="Disable TLS verification"),
    ca_file: str | None = typer.Option(None, "--ca-file", help="CA file path"),
):
    # Read password from file if provided (CLI has priority, but file is still CLI input)
    if api_password_file and not api_password:
        p = Path(api_password_file)
        if not p.exists() or not p.is_file():
            typer.echo(f"ERROR: api-password-file not found: {api_password_file}", err=True)
            raise typer.Exit(code=2)
        api_password = p.read_text(encoding="utf-8").strip()

    if not run_id:
        run_id = str(uuid.uuid4())

    cli_overrides = {
        "host": host,
        "port": port,
        "api_username": api_username,
        "api_password": api_password,
        "log_dir": log_dir,
        "report_dir": report_dir,
        "cache_dir": cache_dir,
        "tls_skip_verify": tls_skip_verify,
        "ca_file": ca_file,
    }
    loaded = load_settings(config_path=config, cli_overrides=cli_overrides)

    # Ensure dirs exist (по ТЗ это важно; на этапе 1 — просто создаём)
    _ensure_dir(loaded.settings.log_dir)
    _ensure_dir(loaded.settings.report_dir)
    _ensure_dir(loaded.settings.cache_dir)

    # прокидываем дальше
    ctx.obj = {
        "run_id": run_id,
        "settings": loaded.settings,
        "sources": loaded.sources_used,
        "config_path": config,
    }


@app.command()
def validate(
    ctx: typer.Context,
    csv: str | None = typer.Option(None, "--csv", help="Path to input CSV"),
):
    _require_csv(csv)
    run_id = ctx.obj["run_id"]
    settings: Settings = ctx.obj["settings"]
    sources = ctx.obj["sources"]
    _print_run_header(run_id, "validate", settings, sources)
    typer.echo("validate: not implemented yet (stage 1)")


@app.command("import")
def import_(
    ctx: typer.Context,
    csv: str | None = typer.Option(None, "--csv", help="Path to input CSV"),
):
    _require_csv(csv)
    run_id = ctx.obj["run_id"]
    settings: Settings = ctx.obj["settings"]
    sources = ctx.obj["sources"]
    _print_run_header(run_id, "import", settings, sources)
    typer.echo("import: not implemented yet (stage 1)")


@app.command("check-api")
def check_api(ctx: typer.Context):
    run_id = ctx.obj["run_id"]
    settings: Settings = ctx.obj["settings"]
    sources = ctx.obj["sources"]
    _require_api(settings)
    _print_run_header(run_id, "check-api", settings, sources)
    typer.echo("check-api: not implemented yet (stage 1)")


@cache_app.command("refresh")
def cache_refresh(ctx: typer.Context):
    run_id = ctx.obj["run_id"]
    settings: Settings = ctx.obj["settings"]
    sources = ctx.obj["sources"]
    _require_api(settings)
    _print_run_header(run_id, "cache refresh", settings, sources)
    typer.echo("cache refresh: not implemented yet (stage 1)")


app.add_typer(cache_app, name="cache")
app.add_typer(user_app, name="user")