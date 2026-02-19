"""
Назначение:
    Delivery-команда применения готового import plan.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
import sqlite3

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.commands.common import log_sqlite_cache_error, result_with, vault_startup_error_result
from connector.delivery.cli.bootstrap import (
    build_cache,
    build_secret_retention_hook,
    build_target_runtime_with_info,
    build_diagnostics_catalog,
    build_secret_provider,
    ensure_vault_startup_ready,
)
from connector.delivery.commands.import_apply_dry_run_executor import DryRunExecutor
from connector.delivery.presenters.apply_report_presenter import ApplyReportPresenter
from connector.delivery.telemetry.apply_logging_sink import LoggingApplyTelemetrySink
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.secrets.errors import (
    SecretKeyConfigError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)
from connector.domain.secrets.policy.rollout_metrics import (
    VaultRolloutThresholds,
    build_vault_operational_metrics,
)
from connector.domain.secrets.policy.rollout_policy import (
    VaultRolloutPolicySettings,
    evaluate_vault_rollout,
)
from connector.domain.secrets.policy.runtime_mode_policy import (
    RUNTIME_REASON_INVALID_MODE,
    VAULT_RUNTIME_MODE_OFF,
    resolve_vault_runtime_mode,
)
from connector.datasets.registry import build_identity_index_plan, get_spec
from connector.infra.artifacts.plan_reader import readPlanFile
from connector.infra.logging.setup import logEvent
from connector.usecases.import_apply_service import ImportApplyService
from connector.usecases.common.identity_sync import IdentityIndexSyncer


@dataclass(frozen=True)
class Options:
    plan_path: str | None = None
    stop_on_first_error: bool | None = None
    max_actions: int | None = None
    dry_run: bool | None = None
    report_items_limit: int | None = None
    secrets_from: str | None = None
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


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    """Собрать runtime/deps и выполнить apply use-case для указанного плана."""
    app_settings = ctx.app_settings
    if app_settings is None:
        raise ValueError("App settings are not initialized")
    run_id = ctx.run_id

    if not opts.plan_path:
        typer.echo("ERROR: --plan is required (apply no longer builds plan from CSV)", err=True)
        return result_with(SystemErrorCode.IO_ERROR)

    report_items_limit = (
        opts.report_items_limit
        if opts.report_items_limit is not None
        else app_settings.observability.report_items_limit
    )
    stop_on_first_error = (
        opts.stop_on_first_error
        if opts.stop_on_first_error is not None
        else app_settings.execution.stop_on_first_error
    )
    max_actions = opts.max_actions if opts.max_actions is not None else app_settings.execution.max_actions
    configured_dry_run = opts.dry_run if opts.dry_run is not None else app_settings.execution.dry_run

    try:
        plan = readPlanFile(opts.plan_path or "")
    except (OSError, ValueError) as exc:
        logEvent(ctx.logger, logging.ERROR, run_id, "plan", f"Import apply failed: {exc}")
        typer.echo(f"ERROR: import apply failed: {exc}", err=True)
        return result_with(SystemErrorCode.IO_ERROR)

    runtime_mode_decision = resolve_vault_runtime_mode(
        mode=opts.vault_mode,
        requires_vault=_plan_requires_vault(plan),
        legacy_force_on=opts.secrets_from == "vault",
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
        settings=_rollout_settings(app_settings),
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
    if rollout_decision.startup_guard_required:
        try:
            ensure_vault_startup_ready(paths_settings=app_settings.paths)
            startup_guard_passed = True
        except _STARTUP_ERRORS as exc:
            startup_guard_passed = False
            return vault_startup_error_result(logger=ctx.logger, run_id=run_id, exc=exc)

    effective_secrets_from = opts.secrets_from
    if rollout_decision.vault_enabled:
        effective_secrets_from = "vault"
    elif effective_secrets_from == "vault":
        effective_secrets_from = "none"
    dry_run = configured_dry_run or rollout_decision.force_dry_run

    dataset_name = plan.meta.dataset
    catalog = ctx.catalog or build_diagnostics_catalog(
        dataset_name,
        strict=app_settings.observability.diagnostics_strict,
    )
    gateway = None
    apply_runtime = None
    runtime = None
    secrets_provider = None
    secret_retention = None
    identity_keys: dict[str, set[str]] = {}
    identity_id_fields: dict[str, str] = {}
    try:
        gateway, cache_roles, _cache_specs = build_cache(app_settings.paths)
        apply_runtime = cache_roles.apply_runtime
        identity_keys, identity_id_fields = build_identity_index_plan()
    except sqlite3.Error as exc:
        log_sqlite_cache_error(logger=ctx.logger, run_id=run_id, exc=exc)
    except Exception as exc:
        logEvent(ctx.logger, logging.ERROR, run_id, "cache", f"Failed to init identity index: {exc}")

    try:
        build_result = build_target_runtime_with_info(
            app_settings.api,
            include_reader=False,
        )
        runtime = build_result.runtime
        target_meta = runtime.meta()
        endpoint = target_meta.endpoint

        report.set_meta(dataset=dataset_name, items_limit=report_items_limit)
        report.set_context(
            "apply",
            {
                "plan_path": opts.plan_path or plan.meta.plan_path,
                "include_deleted": plan.meta.include_deleted,
                "stop_on_first_error": stop_on_first_error,
                "max_actions": max_actions,
                "dry_run": dry_run,
                "configured_dry_run": configured_dry_run,
                "retries": app_settings.api.retries,
                "retry_backoff_seconds": app_settings.api.retry_backoff_seconds,
                "vault_rollout": {
                    "vault_runtime": runtime_mode_decision.to_context(),
                    **rollout_decision.to_context(),
                },
            },
        )
        report.set_context(
            "apply_target",
            {
                "endpoint": endpoint,
                "user": app_settings.api.username,
                "target_runtime_mode": build_result.effective_mode,
            },
        )
        report.set_context("target_runtime", _runtime_context(build_result))

        secrets_provider = build_secret_provider(
            effective_secrets_from,
            paths_settings=app_settings.paths,
            run_id=plan.meta.run_id,
        )
        # Dry-run должен оставаться чистым: retention hooks отключены полностью.
        secret_retention = (
            None
            if dry_run
            else build_secret_retention_hook(
                effective_secrets_from,
                paths_settings=app_settings.paths,
            )
        )
        dataset_spec = get_spec(dataset_name, secrets=secrets_provider)
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
            thresholds=_rollout_thresholds(app_settings),
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
            collector=report,
            plan=plan,
            runtime_context=runtime_context,
        )

        result = CommandResult()
        for code in apply_result.all_codes:
            result.add_code(code)
        return result
    finally:
        if secret_retention is not None:
            close_retention = getattr(secret_retention, "close", None)
            if callable(close_retention):
                close_retention()
        if secrets_provider is not None:
            close = getattr(secrets_provider, "close", None)
            if callable(close):
                close()
        if runtime is not None:
            runtime.close()
        if gateway is not None:
            gateway.close()


def _rollout_settings(app_settings) -> VaultRolloutPolicySettings:
    rollout = app_settings.vault_rollout
    return VaultRolloutPolicySettings(
        mode=rollout.mode,
        canary_percent=rollout.canary_percent,
        canary_datasets=rollout.canary_datasets,
        canary_seed=rollout.canary_seed,
    )


def _plan_requires_vault(plan) -> bool:
    """Назначение:
        Определить необходимость vault-path для apply по содержимому import plan.
    """
    for item in plan.items:
        if item.secret_fields:
            return True
    return False


def _rollout_thresholds(app_settings) -> VaultRolloutThresholds:
    rollout = app_settings.vault_rollout
    return VaultRolloutThresholds(
        row_failure_rate_threshold_pct=rollout.row_failure_rate_threshold_pct,
        vault_error_rate_threshold_pct=rollout.vault_error_rate_threshold_pct,
        latency_regression_threshold_pct=rollout.latency_regression_threshold_pct,
        busy_timeout_rate_threshold_pct=rollout.busy_timeout_rate_threshold_pct,
        schema_changed_rate_threshold_pct=rollout.schema_changed_rate_threshold_pct,
    )

__all__ = ["handler", "Options"]
