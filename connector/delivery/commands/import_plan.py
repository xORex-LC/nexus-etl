from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import typer

from connector.common.time import getNowIso
from connector.delivery.cli.containers import build_dataset_spec, build_diagnostics_catalog
from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.commands.common import (
    attach_dictionary_report_snapshot_if_available,
    result_with,
    sqlite_cache_error_result,
    vault_startup_error_result,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.plan_builder import PlanBuilder
from connector.domain.reporting.contracts import ReportContextKey, ReportItemStatus
from connector.domain.reporting.events import AddItemEvent, SetMetaEvent, SetRowCountersEvent
from connector.domain.reporting.policy import ReportPolicy
from connector.domain.secrets.errors import (
    SecretKeyConfigError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)
from connector.config.projections import to_vault_rollout_policy_settings
from connector.domain.secrets.policy.rollout_policy import evaluate_vault_rollout
from connector.domain.secrets.policy.runtime_mode_policy import (
    RUNTIME_REASON_INVALID_MODE,
    VAULT_RUNTIME_MODE_OFF,
    resolve_vault_runtime_mode,
)
from connector.infra.artifacts.plan_writer import write_plan_file
from connector.infra.logging.setup import logEvent


@dataclass(frozen=True)
class Options:
    source_has_header: bool | None = None
    include_deleted: bool | None = None
    report_items_limit: int | None = None
    report_include_skipped: bool | None = None
    dataset: str | None = None
    vault_mode: str | None = None


_STARTUP_ERRORS = (
    SecretKeyConfigError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)


def handler(ctx: BoundCommandContext, opts: Options, report_sink=None) -> CommandResult:
    """
    Назначение:
        Запустить сценарий import-plan через CLI handler.
    """
    app_config = ctx.app_config
    if app_config is None:
        raise ValueError("App config is not initialized")
    run_id = ctx.run_id

    try:
        dataset_name, _spec = build_dataset_spec(opts.dataset, app_config.dataset)
        runtime_mode_decision = resolve_vault_runtime_mode(
            mode=opts.vault_mode,
            requires_vault=_dataset_requires_vault(_spec),
        )
        if runtime_mode_decision.reason == RUNTIME_REASON_INVALID_MODE:
            typer.echo("ERROR: unsupported --vault-mode, expected one of: auto|on|off", err=True)
            return result_with(SystemErrorCode.INTERNAL_ERROR)
        if runtime_mode_decision.mode == VAULT_RUNTIME_MODE_OFF and runtime_mode_decision.requires_vault:
            typer.echo(
                "ERROR: vault-mode=off cannot be used because dataset declares secret fields",
                err=True,
            )
            return result_with(SystemErrorCode.INTERNAL_ERROR)

        rollout_decision = evaluate_vault_rollout(
            settings=to_vault_rollout_policy_settings(app_config),
            requested_vault=runtime_mode_decision.requested_vault,
            dataset=dataset_name,
            run_id=run_id,
            command_name="import-plan",
        )
        if runtime_mode_decision.requested_vault and not rollout_decision.vault_enabled:
            typer.echo(
                (
                    "ERROR: vault rollout policy blocks import-plan vault path "
                    f"(mode={rollout_decision.mode}, reason={rollout_decision.reason})"
                ),
                err=True,
            )
            return result_with(SystemErrorCode.INTERNAL_ERROR)

        secret_store = None
        if rollout_decision.vault_enabled:
            ctx.container.sqlite.vault_ready.init()
            secret_store = ctx.container.vault.write_service()

        include_deleted_value = (
            opts.include_deleted if opts.include_deleted is not None else app_config.dataset.include_deleted
        )
        report_items_limit_value = (
            opts.report_items_limit
            if opts.report_items_limit is not None
            else app_config.observability.report_items_limit
        )
        source_has_header_value = (
            opts.source_has_header if opts.source_has_header is not None else app_config.dataset.source_has_header
        )

        catalog = build_diagnostics_catalog(
            dataset_name,
            strict=app_config.observability.diagnostics_strict,
        )
        report_policy = ReportPolicy.from_profile(app_config.observability.report_policy_profile)
        if report_sink is not None:
            report_sink.emit(SetMetaEvent(dataset=dataset_name))

        pipeline = ctx.container.pipeline
        with pipeline.dataset_spec.override(_spec), \
             pipeline.run_id.override(run_id), \
             pipeline.source_has_header.override(source_has_header_value), \
             pipeline.catalog.override(catalog), \
             pipeline.include_deleted.override(include_deleted_value), \
             pipeline.secret_store.override(secret_store):

            generated_at = getNowIso()
            plan_pipeline = pipeline.planning_pipeline()
            planning_runtime = ctx.container.cache.roles().planning_runtime
            with plan_pipeline.open(
                run_id=run_id,
                planning_runtime=planning_runtime,
                report_items_limit=report_items_limit_value,
            ) as resolved_rows:
                effective_include_skipped = _resolve_effective_include_skipped_items(
                    opts=opts,
                    app_config=app_config,
                    report_policy=report_policy,
                )
                on_skipped_row = None
                if report_sink is not None:
                    def _on_skipped_row(resolved_row) -> None:
                        _emit_skipped_report_item(
                            report_sink=report_sink,
                            row_ref=resolved_row.row_ref,
                            store=effective_include_skipped,
                        )
                    on_skipped_row = _on_skipped_row
                plan_result = PlanBuilder().build_from_stream(
                    resolved_rows,
                    on_skipped_row=on_skipped_row,
                )
                if report_sink is not None:
                    report_sink.emit(
                        SetRowCountersEvent(
                            rows_total=plan_result.summary.rows_total,
                            rows_passed=plan_result.summary.planned_create + plan_result.summary.planned_update,
                            rows_blocked=plan_result.summary.failed_rows,
                            rows_with_warnings=0,
                            rows_skipped=plan_result.summary.skipped,
                        )
                    )

            plan_meta = {
                "csv_path": None,
                "include_deleted": include_deleted_value,
                "dataset": dataset_name,
            }
            plan_path = write_plan_file(
                plan_items=plan_result.items,
                summary=plan_result.summary_as_dict(),
                meta=plan_meta,
                report_dir=app_config.paths.report_dir,
                run_id=run_id,
                generated_at=generated_at,
            )
            logEvent(ctx.logger, logging.INFO, run_id, "plan", f"Plan written: {plan_path}")
            result = CommandResult()
            result.add_code(SystemErrorCode.OK)
            attach_dictionary_report_snapshot_if_available(ctx=ctx, report_sink=report_sink)
            return result
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    except _STARTUP_ERRORS as exc:
        return vault_startup_error_result(logger=ctx.logger, run_id=run_id, exc=exc)
    except sqlite3.Error as exc:
        return sqlite_cache_error_result(logger=ctx.logger, run_id=run_id, scope="plan", exc=exc)
    except Exception as exc:
        logEvent(ctx.logger, logging.ERROR, run_id, "plan", f"Import plan failed: {exc}")
        typer.echo("ERROR: import plan failed (see logs)", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)


def _dataset_requires_vault(dataset_spec) -> bool:
    """Назначение:
        Проверить, нужны ли secret-store операции в transform/enrich перед планированием.
    """
    enrich_spec = dataset_spec.build_spec_for("enrich")
    secrets = enrich_spec.enrich.secrets
    if secrets is not None:
        for field in secrets.fields:
            if isinstance(field, str) and field.strip():
                return True
    for rule in (*enrich_spec.enrich.generate, *enrich_spec.enrich.lookup):
        target = str(rule.target or "").strip()
        if target.startswith("secret:"):
            return True
    return False


def _emit_skipped_report_item(*, report_sink, row_ref, store: bool) -> None:
    report_sink.emit(
        AddItemEvent(
            status=ReportItemStatus.SKIPPED,
            row_ref=row_ref,
            payload=None,
            errors=(),
            warnings=(),
            meta={"op": "skip"},
            store=store,
            preaggregated=True,
        )
    )


def _resolve_effective_include_skipped_items(
    *,
    opts: Options,
    app_config,
    report_policy: ReportPolicy,
) -> bool:
    cli_include_skipped = (
        app_config.observability.report_include_skipped
        if opts.report_include_skipped is None
        else bool(opts.report_include_skipped)
    )
    return report_policy.resolve_include_skipped_items(cli_include_skipped)


__all__ = ["handler", "Options"]
