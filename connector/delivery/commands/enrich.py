from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.cli.pipeline_config import CheckpointName
from connector.delivery.commands.common import (
    attach_dictionary_report_snapshot_if_available,
    result_with,
    sqlite_cache_error_result,
    vault_startup_error_result,
)
from connector.delivery.cli.containers import (
    build_dataset_spec,
    build_diagnostics_catalog,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.reporting.contracts import ReportContextKey
from connector.domain.reporting.events import SetContextEvent, SetMetaEvent
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
from connector.usecases.enrich_usecase import EnrichUseCase


@dataclass(frozen=True)
class Options:
    csv_has_header: bool | None = None
    dataset: str | None = None
    report_items_limit: int | None = None
    include_enriched_items: bool | None = None
    vault_mode: str | None = None


_STARTUP_ERRORS = (
    SecretKeyConfigError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)


def handler(ctx: BoundCommandContext, opts: Options, report_sink) -> CommandResult:
    run_id = ctx.run_id
    app_config = ctx.app_config
    if app_config is None:
        raise ValueError("App config is not initialized")

    csv_has_header_value = (
        opts.csv_has_header if opts.csv_has_header is not None else app_config.dataset.csv_has_header
    )
    report_items_limit_value = (
        opts.report_items_limit
        if opts.report_items_limit is not None
        else app_config.observability.report_items_limit
    )
    include_enriched_items_value = opts.include_enriched_items if opts.include_enriched_items is not None else True

    dataset_name, dataset_spec = build_dataset_spec(opts.dataset, app_config.dataset)
    runtime_mode_decision = resolve_vault_runtime_mode(
        mode=opts.vault_mode,
        requires_vault=_dataset_requires_vault(dataset_spec),
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
        command_name="enrich",
    )
    if runtime_mode_decision.requested_vault and not rollout_decision.vault_enabled:
        typer.echo(
            (
                "ERROR: vault rollout policy blocks enrich vault path "
                f"(mode={rollout_decision.mode}, reason={rollout_decision.reason})"
            ),
            err=True,
        )
        return result_with(SystemErrorCode.INTERNAL_ERROR)

    secret_store = None
    if rollout_decision.vault_enabled:
        try:
            ctx.container.sqlite.vault_ready.init()
        except _STARTUP_ERRORS as exc:
            return vault_startup_error_result(logger=ctx.logger, run_id=run_id, exc=exc)
        secret_store = ctx.container.vault.write_service()

    catalog = ctx.catalog or build_diagnostics_catalog(
        dataset_name,
        strict=app_config.observability.diagnostics_strict,
    )
    report_sink.emit(SetMetaEvent(dataset=dataset_name))
    report_sink.emit(
        SetContextEvent(
            name=ReportContextKey.VAULT_ROLLOUT,
            value={
                "vault_runtime": runtime_mode_decision.to_context(),
                **rollout_decision.to_context(),
                "command": "enrich",
            },
        )
    )
    report_policy = ReportPolicy.from_profile(app_config.observability.report_policy_profile)

    try:
        pipeline = ctx.container.pipeline
        composer = pipeline.pipeline_composer()
        with pipeline.dataset_spec.override(dataset_spec), \
             pipeline.run_id.override(run_id), \
             pipeline.csv_has_header.override(csv_has_header_value), \
             pipeline.catalog.override(catalog), \
             pipeline.secret_store.override(secret_store):
            usecase = EnrichUseCase(
                report_items_limit=report_items_limit_value,
                include_enriched_items=include_enriched_items_value,
            )
            result = usecase.run(
                row_source=pipeline.row_source(),
                pipeline=composer.compose(CheckpointName.ENRICH),
                dataset=dataset_name,
                logger=ctx.logger,
                run_id=run_id,
                report_sink=report_sink,
                report_policy=report_policy,
                catalog=catalog,
            )
            attach_dictionary_report_snapshot_if_available(ctx=ctx, report_sink=report_sink)
            return result
    except sqlite3.Error as exc:
        return sqlite_cache_error_result(logger=ctx.logger, run_id=run_id, scope="enrich", exc=exc)


def _dataset_requires_vault(dataset_spec) -> bool:
    """Назначение:
        Определить, содержит ли enrich DSL секретные назначения.

    Контракт:
        - учитывает декларативный `enrich.secrets.fields`;
        - учитывает явные `target: secret:<field>` в generate/lookup.
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
