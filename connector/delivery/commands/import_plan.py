from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import typer

from connector.common.time import getNowIso
from connector.delivery.cli.containers import build_dataset_spec, build_diagnostics_catalog
from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.commands.common import result_with, sqlite_cache_error_result, vault_startup_error_result
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.planning.plan_builder import PlanBuilder
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.stages.stages import PipelineOrchestrator
from connector.domain.secrets.errors import (
    SecretKeyConfigError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
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
from connector.infra.artifacts.plan_writer import write_plan_file
from connector.infra.logging.setup import logEvent
from connector.usecases.planning_match_runtime import open_match_runtime, iter_matched_ok
from connector.usecases.resolve_usecase import ResolveUseCase


@dataclass(frozen=True)
class Options:
    csv_has_header: bool | None = None
    include_deleted: bool | None = None
    report_items_limit: int | None = None
    dataset: str | None = None
    vault_mode: str | None = None


_STARTUP_ERRORS = (
    SecretKeyConfigError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)


def handler(ctx: BoundCommandContext, opts: Options) -> CommandResult:
    """
    Назначение:
        Запустить сценарий import-plan через CLI handler.
    """
    app_settings = ctx.app_settings
    if app_settings is None:
        raise ValueError("App settings are not initialized")
    run_id = ctx.run_id

    try:
        dataset_name, _spec = build_dataset_spec(opts.dataset, app_settings.dataset)
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
            settings=_rollout_settings(app_settings),
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

        cache_roles = ctx.container.cache.roles()

        include_deleted_value = (
            opts.include_deleted if opts.include_deleted is not None else app_settings.dataset.include_deleted
        )
        report_items_limit_value = (
            opts.report_items_limit
            if opts.report_items_limit is not None
            else app_settings.observability.report_items_limit
        )
        csv_has_header_value = (
            opts.csv_has_header if opts.csv_has_header is not None else app_settings.dataset.csv_has_header
        )

        catalog = build_diagnostics_catalog(
            dataset_name,
            strict=app_settings.observability.diagnostics_strict,
        )

        pipeline = ctx.container.pipeline
        with pipeline.dataset_spec.override(_spec), \
             pipeline.run_id.override(run_id), \
             pipeline.csv_has_header.override(csv_has_header_value), \
             pipeline.catalog.override(catalog), \
             pipeline.include_deleted.override(include_deleted_value), \
             pipeline.secret_store.override(secret_store):

            row_source = pipeline.row_source()
            map_stage = pipeline.map_stage()
            normalize_stage = pipeline.normalize_stage()
            enrich_stage = pipeline.enrich_stage()
            match_stage = pipeline.match_stage()
            resolve_stage = pipeline.resolve_stage()
            transform_pipeline = PipelineOrchestrator([map_stage, normalize_stage, enrich_stage])

            generated_at = getNowIso()
            extractor = Extractor(row_source, catalog=catalog)
            enriched_rows = iter_ok(
                transform_pipeline.run(extractor.run()),
                should_skip=lambda item: item.row is None,
            )

            with open_match_runtime(
                run_id=run_id,
                match_stage=match_stage,
                match_runtime=cache_roles.planning_runtime,
                report_items_limit=report_items_limit_value,
                include_matched_items=False,
                batch_size=app_settings.matching_runtime.match_batch_size,
                flush_interval_ms=app_settings.matching_runtime.match_flush_interval_ms,
            ) as match_runtime:
                matched_rows = iter_matched_ok(
                    runtime=match_runtime,
                    enriched_source=enriched_rows,
                )

                resolve_usecase = ResolveUseCase(
                    report_items_limit=report_items_limit_value,
                    include_resolved_items=False,
                    batch_size=app_settings.matching_runtime.resolve_batch_size,
                    flush_interval_ms=app_settings.matching_runtime.resolve_flush_interval_ms,
                )
                resolved_rows = iter_ok(
                    resolve_usecase.iter_resolved(
                        matched_source=matched_rows,
                        resolve_stage=resolve_stage,
                        dataset=dataset_name,
                        pending_replay=cache_roles.planning_runtime,
                    )
                )

                plan_result = PlanBuilder().build_from_stream(resolved_rows)

            plan_meta = {
                "csv_path": None,
                "include_deleted": include_deleted_value,
                "dataset": dataset_name,
            }
            plan_path = write_plan_file(
                plan_items=plan_result.items,
                summary=plan_result.summary_as_dict(),
                meta=plan_meta,
                report_dir=app_settings.paths.report_dir,
                run_id=run_id,
                generated_at=generated_at,
            )
            logEvent(ctx.logger, logging.INFO, run_id, "plan", f"Plan written: {plan_path}")
            result = CommandResult()
            result.add_code(SystemErrorCode.OK)
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


def _rollout_settings(app_settings) -> VaultRolloutPolicySettings:
    rollout = app_settings.vault_rollout
    return VaultRolloutPolicySettings(
        mode=rollout.mode,
        canary_percent=rollout.canary_percent,
        canary_datasets=rollout.canary_datasets,
        canary_seed=rollout.canary_seed,
    )


def _dataset_requires_vault(dataset_spec) -> bool:
    """Назначение:
        Проверить, нужны ли secret-store операции в transform/enrich перед планированием.
    """
    enrich_spec = dataset_spec.build_enrich_spec()
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


__all__ = ["handler", "Options"]
