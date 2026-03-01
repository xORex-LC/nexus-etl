from __future__ import annotations

import logging

import typer

from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.reporting.contracts import ReportContextKey
from connector.domain.reporting.events import SetContextEvent
from connector.domain.secrets.errors import VaultDomainError
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


def vault_startup_error_result(*, logger, run_id: str, exc: VaultDomainError) -> CommandResult:
    """
    Назначение:
        Единый fail-fast результат для startup guard ошибок (`VAULT_STARTUP_*`).
    """
    logEvent(logger, logging.ERROR, run_id, "vault", f"{exc.code}: {exc}")
    typer.echo(f"ERROR: {exc.code}: {exc}", err=True)
    return result_with(SystemErrorCode.INTERNAL_ERROR)


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


def attach_dictionary_report_snapshot_if_available(*, ctx, report_sink) -> None:
    """
    Назначение:
        Best-effort записать snapshot dictionary telemetry в report context.

    Граница ответственности:
        - Читает telemetry через DI container (`ctx.container.dictionary.telemetry()`).
        - Не расширяет `DictionaryProviderPort` ради отчётности.
        - Безопасно no-op, если report/container/dictionary telemetry недоступны.
    """
    if report_sink is None:
        return

    container = getattr(ctx, "container", None)
    if container is None:
        return

    dictionary_container = getattr(container, "dictionary", None)
    if dictionary_container is None:
        return

    telemetry_provider = getattr(dictionary_container, "telemetry", None)
    if telemetry_provider is None:
        return

    telemetry = telemetry_provider()
    if telemetry is None:
        return

    snapshot = telemetry.snapshot()
    if isinstance(snapshot, dict):
        report_sink.emit(SetContextEvent(name=ReportContextKey.DICTIONARY, value=snapshot))
