from __future__ import annotations

import logging
from dataclasses import dataclass
import sqlite3

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.commands.common import log_sqlite_cache_error, result_with
from connector.delivery.cli.bootstrap import (
    build_cache,
    build_api_client,
    build_api_executor,
    build_diagnostics_catalog,
    build_secret_provider,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.datasets.registry import build_identity_index_plan, get_spec
from connector.infra.artifacts.plan_reader import readPlanFile
from connector.infra.logging.setup import logEvent
from connector.usecases.import_apply_service import ImportApplyService


@dataclass(frozen=True)
class Options:
    plan_path: str | None = None
    stop_on_first_error: bool | None = None
    max_actions: int | None = None
    dry_run: bool | None = None
    report_items_limit: int | None = None
    resource_exists_retries: int | None = None
    secrets_from: str | None = None
    vault_file: str | None = None


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    settings = ctx.settings
    run_id = ctx.run_id

    if not opts.plan_path:
        typer.echo("ERROR: --plan is required (apply no longer builds plan from CSV)", err=True)
        return result_with(SystemErrorCode.IO_ERROR)

    report_items_limit = opts.report_items_limit if opts.report_items_limit is not None else settings.report_items_limit
    resource_exists_retries = (
        opts.resource_exists_retries if opts.resource_exists_retries is not None else settings.resource_exists_retries
    )
    stop_on_first_error = opts.stop_on_first_error if opts.stop_on_first_error is not None else settings.stop_on_first_error
    max_actions = opts.max_actions if opts.max_actions is not None else settings.max_actions
    dry_run = opts.dry_run if opts.dry_run is not None else settings.dry_run

    try:
        plan = readPlanFile(opts.plan_path or "")
    except (OSError, ValueError) as exc:
        logEvent(ctx.logger, logging.ERROR, run_id, "plan", f"Import apply failed: {exc}")
        typer.echo(f"ERROR: import apply failed: {exc}", err=True)
        return result_with(SystemErrorCode.IO_ERROR)

    dataset_name = plan.meta.dataset
    catalog = ctx.catalog or build_diagnostics_catalog(dataset_name, strict=settings.diagnostics_strict)
    gateway = None
    apply_runtime = None
    identity_keys: dict[str, set[str]] = {}
    identity_id_fields: dict[str, str] = {}
    try:
        gateway, cache_roles, _cache_specs = build_cache(settings)
        apply_runtime = cache_roles.apply_runtime
        identity_keys, identity_id_fields = build_identity_index_plan()
    except sqlite3.Error as exc:
        log_sqlite_cache_error(logger=ctx.logger, run_id=run_id, exc=exc)
    except Exception as exc:
        logEvent(ctx.logger, logging.ERROR, run_id, "cache", f"Failed to init identity index: {exc}")

    try:
        base_url = f"https://{settings.host}:{settings.port}"
        report.set_meta(dataset=dataset_name, items_limit=report_items_limit)
        report.set_context(
            "apply",
            {
                "plan_path": opts.plan_path or plan.meta.plan_path,
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

        client = build_api_client(settings)
        client.resetRetryAttempts()
        secrets_provider = build_secret_provider(opts.secrets_from, opts.vault_file)
        executor = build_api_executor(client)
        service = ImportApplyService(
            executor,
            secrets=secrets_provider,
            spec_resolver=get_spec,
            apply_runtime=apply_runtime,
            identity_keys=identity_keys,
            identity_id_fields=identity_id_fields,
        )
        result = service.applyPlan(
            plan=plan,
            logger=ctx.logger,
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
        return result
    finally:
        if gateway is not None:
            gateway.close()

__all__ = ["handler", "Options"]
