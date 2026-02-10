from __future__ import annotations

import logging

import typer

from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.logging.setup import logEvent


def result_with(code: SystemErrorCode) -> CommandResult:
    """
    Назначение:
        Построить `CommandResult` с единственным системным кодом.
    """
    result = CommandResult()
    result.add_code(code)
    return result


def sqlite_cache_error_result(*, logger, run_id: str, scope: str, exc: Exception) -> CommandResult:
    """
    Назначение:
        Единый fallback для ошибок открытия/чтения cache DB.
    """
    logEvent(logger, logging.ERROR, run_id, "cache", f"Failed to open cache DB: {exc}")
    typer.echo("ERROR: failed to open cache DB (see logs/report)", err=True)
    return result_with(SystemErrorCode.CACHE_ERROR)


def log_sqlite_cache_error(*, logger, run_id: str, exc: Exception) -> None:
    """
    Назначение:
        Единый логгер cache sqlite-ошибки для best-effort сценариев.
    """
    logEvent(logger, logging.ERROR, run_id, "cache", f"Failed to open cache DB: {exc}")


def ensure_supported_cache_dataset(cache_admin, dataset: str | None) -> CommandResult | None:
    """
    Назначение:
        Проверить, что dataset поддерживается cache admin портом.
    """
    if dataset is None:
        return None
    if dataset in cache_admin.list_datasets():
        return None
    typer.echo(f"ERROR: Unsupported cache dataset: {dataset}", err=True)
    return result_with(SystemErrorCode.CACHE_ERROR)
