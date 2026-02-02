from __future__ import annotations

import logging
import sqlite3

import typer

from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.secrets import SecretProviderProtocol
from connector.datasets.registry import build_identity_index_plan, get_spec
from connector.delivery.bootstrap import build_diagnostics_catalog
from connector.infra.artifacts.plan_reader import readPlanFile
from connector.infra.cache.db import getCacheDbPath, openCacheDb
from connector.infra.cache.identity_repository import SqliteIdentityRepository
from connector.infra.cache.pending_links_repository import SqlitePendingLinksRepository
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.http.ankey_client import AnkeyApiClient
from connector.infra.http.request_executor import AnkeyRequestExecutor
from connector.infra.logging.setup import logEvent
from connector.infra.secrets import NullSecretProvider, PromptSecretProvider, CompositeSecretProvider
from connector.usecases.import_apply_service import ImportApplyService
from connector.datasets.cache_registry import list_cache_specs


def run(
    *,
    ctx: typer.Context,
    plan_path: str | None,
    stop_on_first_error: bool | None,
    max_actions: int | None,
    dry_run: bool | None,
    report_items_limit: int | None,
    resource_exists_retries: int | None,
    secrets_from: str | None,
    vault_file: str | None,
    logger,
    report,
) -> CommandResult:
    settings = ctx.obj["settings"]
    run_id = ctx.obj["runId"]
    cache_db_path = getCacheDbPath(settings.cache_dir)

    if not plan_path:
        typer.echo("ERROR: --plan is required (apply no longer builds plan from CSV)", err=True)
        return _result_with(SystemErrorCode.IO_ERROR)

    report_items_limit = report_items_limit if report_items_limit is not None else settings.report_items_limit
    resource_exists_retries = (
        resource_exists_retries if resource_exists_retries is not None else settings.resource_exists_retries
    )
    stop_on_first_error = stop_on_first_error if stop_on_first_error is not None else settings.stop_on_first_error
    max_actions = max_actions if max_actions is not None else settings.max_actions
    dry_run = dry_run if dry_run is not None else settings.dry_run

    try:
        plan = readPlanFile(plan_path or "")
    except (OSError, ValueError) as exc:
        logEvent(logger, logging.ERROR, run_id, "plan", f"Import apply failed: {exc}")
        typer.echo(f"ERROR: import apply failed: {exc}", err=True)
        return _result_with(SystemErrorCode.IO_ERROR)

    dataset_name = plan.meta.dataset
    catalog = build_diagnostics_catalog(dataset_name, strict=settings.diagnostics_strict)
    conn = None
    identity_repo = None
    pending_repo = None
    identity_keys: dict[str, set[str]] = {}
    identity_id_fields: dict[str, str] = {}
    try:
        conn = openCacheDb(cache_db_path)
        engine = SqliteEngine(conn)
        cache_specs = list_cache_specs()
        ensure_cache_ready(engine, cache_specs)
        identity_repo = SqliteIdentityRepository(engine)
        pending_repo = SqlitePendingLinksRepository(engine)
        identity_keys, identity_id_fields = build_identity_index_plan()
    except sqlite3.Error as exc:
        logEvent(logger, logging.ERROR, run_id, "cache", f"Failed to open cache DB: {exc}")
    except Exception as exc:
        logEvent(logger, logging.ERROR, run_id, "cache", f"Failed to init identity index: {exc}")

    base_url = f"https://{settings.host}:{settings.port}"
    report.set_meta(dataset=dataset_name, items_limit=report_items_limit)
    report.set_context(
        "apply",
        {
            "plan_path": plan_path or plan.meta.plan_path,
            "include_deleted": plan.meta.include_deleted,
            "stop_on_first_error": stop_on_first_error,
            "max_actions": max_actions,
            "dry_run": dry_run,
            "resource_exists_retries": resource_exists_retries,
            "retries": settings.retries,
            "retry_backoff_seconds": settings.retry_backoff_seconds,
        },
    )
    report.set_context("apply_target", {"base_url": base_url, "user": settings.api_username})

    report.summary.planned_create = plan.summary.planned_create if plan.summary else 0
    report.summary.planned_update = plan.summary.planned_update if plan.summary else 0
    report.summary.skipped = plan.summary.skipped if plan.summary else 0
    report.summary.failed = plan.summary.failed_rows if plan.summary else 0

    client = AnkeyApiClient(
        baseUrl=base_url,
        username=settings.api_username or "",
        password=settings.api_password or "",
        timeoutSeconds=settings.timeout_seconds,
        tlsSkipVerify=settings.tls_skip_verify,
        caFile=settings.ca_file,
        retries=settings.retries,
        retryBackoffSeconds=settings.retry_backoff_seconds,
    )
    client.resetRetryAttempts()
    secrets_provider = build_secret_provider(secrets_from, vault_file)
    executor = AnkeyRequestExecutor(client)
    service = ImportApplyService(
        executor,
        secrets=secrets_provider,
        spec_resolver=get_spec,
        identity_repo=identity_repo,
        identity_keys=identity_keys,
        identity_id_fields=identity_id_fields,
        pending_repo=pending_repo,
    )
    result = service.applyPlan(
        plan=plan,
        logger=logger,
        report=report,
        run_id=run_id,
        stop_on_first_error=stop_on_first_error,
        max_actions=max_actions,
        dry_run=dry_run,
        report_items_limit=report_items_limit,
        resource_exists_retries=resource_exists_retries,
        catalog=catalog,
    )
    if hasattr(client, "getRetryAttempts"):
        report.set_context("apply_runtime", {"retries_used": client.getRetryAttempts()})
    if conn is not None:
        conn.close()
    return result


def build_secret_provider(source: str | None, vault_file: str | None) -> SecretProviderProtocol:
    """
    Назначение:
        Фабрика провайдера секретов для apply.
    Контракт:
        - source None/"none" -> NullSecretProvider
        - source "prompt" -> PromptSecretProvider
        - source "vault" -> CompositeSecretProvider(FileVault -> Prompt)
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


def _result_with(code: SystemErrorCode) -> CommandResult:
    result = CommandResult()
    result.add_code(code)
    return result


__all__ = ["run"]
