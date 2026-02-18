from __future__ import annotations

import logging
import sqlite3
from dataclasses import dataclass

import typer

from connector.delivery.cli.bootstrap import (
    build_cache,
    build_dataset_spec,
    ensure_vault_startup_ready,
    open_secret_store,
)
from connector.delivery.cli.context import CommandContext
from connector.delivery.commands.common import result_with, sqlite_cache_error_result, vault_startup_error_result
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.secrets.errors import (
    SecretKeyConfigError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)
from connector.infra.logging.setup import logEvent
from connector.usecases.import_plan_service import ImportPlanService


@dataclass(frozen=True)
class Options:
    csv_has_header: bool | None = None
    include_deleted: bool | None = None
    report_items_limit: int | None = None
    dataset: str | None = None
    vault_file: str | None = None


_STARTUP_ERRORS = (
    SecretKeyConfigError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)


def handler(ctx: CommandContext, opts: Options) -> CommandResult:
    """
    Назначение:
        Запустить сценарий import-plan через CLI handler.
    """
    app_settings = ctx.app_settings
    if app_settings is None:
        raise ValueError("App settings are not initialized")
    run_id = ctx.run_id

    gateway = None
    try:
        if opts.vault_file:
            ensure_vault_startup_ready(paths_settings=app_settings.paths)

        dataset_name, _spec = build_dataset_spec(opts.dataset, app_settings.dataset)
        gateway, cache_roles, _cache_specs = build_cache(app_settings.paths)

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

        with open_secret_store(
            paths_settings=app_settings.paths,
            enabled=bool(opts.vault_file),
        ) as secret_store:
            service = ImportPlanService()
            return service.run(
                pending_replay=cache_roles.pending_replay,
                enrich_lookup=cache_roles.enrich_lookup,
                planning_runtime=cache_roles.planning_runtime,
                csv_has_header=csv_has_header_value,
                include_deleted=include_deleted_value,
                observability_settings=app_settings.observability,
                pending_settings=app_settings.pending,
                matching_runtime_settings=app_settings.matching_runtime,
                dataset=dataset_name,
                logger=ctx.logger,
                run_id=run_id,
                report_items_limit=report_items_limit_value,
                report_dir=app_settings.paths.report_dir,
                secret_store=secret_store,
            )
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
    finally:
        if gateway is not None:
            gateway.close()


__all__ = ["handler", "Options"]
