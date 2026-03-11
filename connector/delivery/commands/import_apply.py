"""
Назначение:
    Delivery-команда применения готового import plan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
import sqlite3

import typer

from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.cli.containers import build_diagnostics_catalog
from connector.delivery.commands.common import log_sqlite_cache_error, result_with, vault_startup_error_result
from connector.delivery.commands.import_apply_dry_run_executor import DryRunExecutor
from connector.delivery.presenters.apply_report_presenter import ApplyReportPresenter
from connector.delivery.telemetry.apply_logging_sink import LoggingApplyTelemetrySink
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.reporting.contracts import ReportContextKey
from connector.domain.reporting.events import SetContextEvent, SetMetaEvent
from connector.domain.secrets.errors import (
    SecretKeyConfigError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)
from connector.domain.secrets.policy.rollout_metrics import build_vault_operational_metrics
from connector.config.projections import (
    to_vault_rollout_policy_settings,
    to_vault_rollout_thresholds,
)
from connector.domain.secrets.policy.rollout_policy import evaluate_vault_rollout
from connector.domain.secrets.policy.runtime_mode_policy import (
    RUNTIME_REASON_INVALID_MODE,
    VAULT_RUNTIME_MODE_OFF,
    resolve_vault_runtime_mode,
)
from connector.datasets.registry import build_identity_index_plan, get_spec
from connector.infra.artifacts.plan_reader import readPlanFile
from connector.infra.logging.setup import log_event
from connector.usecases.import_apply_service import ImportApplyService
from connector.usecases.common.identity_sync import IdentityIndexSyncer


@dataclass(frozen=True)
class Options:
    plan_path: str | None = None
    stop_on_first_error: bool | None = None
    max_actions: int | None = None
    dry_run: bool | None = None
    report_items_limit: int | None = None
    vault_mode: str | None = None


_STARTUP_ERRORS = (
    SecretKeyConfigError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)


def _runtime_context(build_result) -> dict[str, str]:
    return {
        "target_runtime_mode": build_result.effective_mode,
        "target_runtime_requested_mode": build_result.requested_mode,
    }


def handler(ctx: BoundCommandContext, opts: Options, report_sink) -> CommandResult:
    """Собрать runtime/deps и выполнить apply use-case для указанного плана."""
    app_config = ctx.app_config
    if app_config is None:
        raise ValueError("App config is not initialized")
    run_id = ctx.run_id

    if not opts.plan_path:
        typer.echo("ERROR: --plan is required (apply no longer builds plan from CSV)", err=True)
        return result_with(SystemErrorCode.IO_ERROR)

    report_items_limit = (
        opts.report_items_limit
        if opts.report_items_limit is not None
        else app_config.observability.report_items_limit
    )
    stop_on_first_error = (
        opts.stop_on_first_error
        if opts.stop_on_first_error is not None
        else app_config.execution.stop_on_first_error
    )
    max_actions = opts.max_actions if opts.max_actions is not None else app_config.execution.max_actions
    configured_dry_run = opts.dry_run if opts.dry_run is not None else app_config.execution.dry_run

    try:
        plan = readPlanFile(opts.plan_path or "")
    except (OSError, ValueError) as exc:
        log_event(ctx.logger, logging.ERROR, run_id, "plan", f"Import apply failed: {exc}")
        typer.echo(f"ERROR: import apply failed: {exc}", err=True)
        return result_with(SystemErrorCode.IO_ERROR)

    runtime_mode_decision = resolve_vault_runtime_mode(
        mode=opts.vault_mode,
        requires_vault=_plan_requires_vault(plan),
    )
    if runtime_mode_decision.reason == RUNTIME_REASON_INVALID_MODE:
        typer.echo("ERROR: unsupported --vault-mode, expected one of: auto|on|off", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    if runtime_mode_decision.mode == VAULT_RUNTIME_MODE_OFF and runtime_mode_decision.requires_vault:
        typer.echo(
            "ERROR: vault-mode=off cannot be used because plan contains secret_fields",
            err=True,
        )
        return result_with(SystemErrorCode.INTERNAL_ERROR)

    rollout_decision = evaluate_vault_rollout(
        settings=to_vault_rollout_policy_settings(app_config),
        requested_vault=runtime_mode_decision.requested_vault,
        dataset=plan.meta.dataset,
        run_id=plan.meta.run_id or run_id,
        command_name="import-apply",
    )
    if runtime_mode_decision.requested_vault and not rollout_decision.vault_enabled:
        typer.echo(
            (
                "ERROR: vault rollout policy blocks import-apply vault path "
                f"(mode={rollout_decision.mode}, reason={rollout_decision.reason})"
            ),
            err=True,
        )
        return result_with(SystemErrorCode.INTERNAL_ERROR)

    startup_guard_passed = True
    if rollout_decision.vault_enabled:
        try:
            ctx.container.sqlite.vault_ready.init()
        except _STARTUP_ERRORS as exc:
            startup_guard_passed = False
            return vault_startup_error_result(logger=ctx.logger, run_id=run_id, exc=exc)

    dry_run = configured_dry_run or rollout_decision.force_dry_run

    dataset_name = plan.meta.dataset
    catalog = ctx.catalog or build_diagnostics_catalog(
        dataset_name,
        strict=app_config.observability.diagnostics_strict,
    )

    cache_roles = ctx.container.cache.roles()
    apply_runtime = cache_roles.apply_runtime
    identity_keys: dict[str, set[str]] = {}
    identity_id_fields: dict[str, str] = {}
    try:
        identity_keys, identity_id_fields = build_identity_index_plan()
    except Exception as exc:
        log_event(ctx.logger, logging.ERROR, run_id, "cache", f"Failed to init identity index: {exc}")

    build_result = ctx.container.target.runtime()
    runtime = build_result.runtime
    target_meta = runtime.meta()
    endpoint = target_meta.endpoint

    report_sink.emit(SetMetaEvent(dataset=dataset_name))
    apply_context = {
        "plan_path": opts.plan_path or plan.meta.plan_path,
        "include_deleted": plan.meta.include_deleted,
        "stop_on_first_error": stop_on_first_error,
        "max_actions": max_actions,
        "dry_run": dry_run,
        "configured_dry_run": configured_dry_run,
        "retries": app_config.api.retries,
        "retry_backoff_seconds": app_config.api.retry_backoff_seconds,
        "vault_rollout": {
            "vault_runtime": runtime_mode_decision.to_context(),
            **rollout_decision.to_context(),
        },
    }
    report_sink.emit(
        SetContextEvent(
            name=ReportContextKey.APPLY_TARGET,
            value={
                "endpoint": endpoint,
                "user": app_config.api.username,
                "target_runtime_mode": build_result.effective_mode,
            },
        )
    )
    report_sink.emit(
        SetContextEvent(
            name=ReportContextKey.TARGET_RUNTIME,
            value=_runtime_context(build_result),
        )
    )

    # Dry-run должен оставаться чистым: retention hooks отключены полностью.
    secret_retention = (
        None
        if dry_run or not rollout_decision.vault_enabled
        else ctx.container.vault.retention_service()
    )
    if rollout_decision.vault_enabled:
        dataset_spec = get_spec(dataset_name, secrets=ctx.container.vault.read_service(default_run_id=plan.meta.run_id))
    else:
        dataset_spec = get_spec(dataset_name)
    apply_adapter = dataset_spec.get_apply_adapter()
    executor = DryRunExecutor() if dry_run else runtime.executor
    identity_syncer = (
        IdentityIndexSyncer(
            runtime=apply_runtime,
            identity_keys=identity_keys,
            identity_id_fields=identity_id_fields,
        )
        if apply_runtime is not None
        else None
    )

    telemetry_sink = LoggingApplyTelemetrySink(
        logger=ctx.logger,
        run_id=run_id,
        dataset=dataset_name,
    )

    service = ImportApplyService(
        executor,
        identity_syncer=identity_syncer,
        secret_retention=secret_retention,
        allow_post_success_side_effects=not dry_run,
    )
    apply_result = service.apply_plan(
        plan=plan,
        catalog=catalog,
        apply_adapter=apply_adapter,
        stop_on_first_error=stop_on_first_error,
        max_actions=max_actions,
        max_item_outcomes=report_items_limit,
        telemetry=telemetry_sink,
    )

    maintenance_stats = (
        {}
        if dry_run or secret_retention is None
        else secret_retention.run_maintenance()
    )
    operational_metrics = build_vault_operational_metrics(
        summary=apply_result.summary,
        startup_guard_passed=startup_guard_passed,
        thresholds=to_vault_rollout_thresholds(app_config),
    )
    runtime_context: dict = {
        "retries_used": runtime.stats().retries_total,
        "target_runtime_mode": build_result.effective_mode,
        "target_runtime_requested_mode": build_result.requested_mode,
        "vault_maintenance": dict(maintenance_stats),
        "vault_rollout": {
            "vault_runtime": runtime_mode_decision.to_context(),
            **rollout_decision.to_context(),
        },
        "vault_operational": operational_metrics,
    }

    ApplyReportPresenter.present(
        result=apply_result,
        sink=report_sink,
        plan=plan,
        apply_context=apply_context,
        runtime_context=runtime_context,
    )

    result = CommandResult()
    for code in apply_result.all_codes:
        result.add_code(code)
    return result


def _plan_requires_vault(plan) -> bool:
    """Назначение:
        Определить необходимость vault-path для apply по содержимому import plan.
    """
    for item in plan.items:
        if item.secret_fields:
            return True
    return False


__all__ = ["handler", "Options"]
