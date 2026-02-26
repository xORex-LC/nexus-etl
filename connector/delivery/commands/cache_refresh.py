"""
Назначение:
    Delivery-команда обновления cache-слоя из target-системы.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import BoundCommandContext
from connector.delivery.commands.common import ensure_supported_cache_dataset, result_with
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.datasets.registry import build_identity_index_plan
from connector.infra.cache.dsl_runtime import build_sync_adapters
from connector.infra.logging.setup import logEvent
from connector.usecases.cache_command_service import CacheCommandService
from connector.usecases.cache_refresh_service import CacheRefreshUseCase
from connector.usecases.common.identity_sync import IdentityIndexSyncer


@dataclass(frozen=True)
class Options:
    page_size: int | None = None
    max_pages: int | None = None
    timeout_seconds: float | None = None
    retries: int | None = None
    retry_backoff_seconds: float | None = None
    api_transport: object | None = None
    include_deleted: bool | None = None
    include_dependencies: bool | None = None
    report_items_limit: int | None = None
    dataset: str | None = None


def _runtime_context(build_result) -> dict[str, str]:
    return {
        "target_runtime_mode": build_result.effective_mode,
        "target_runtime_requested_mode": build_result.requested_mode,
    }


def handler(ctx: BoundCommandContext, opts: Options, report) -> CommandResult:
    """Собрать runtime/deps и запустить cache refresh use-case."""
    app_config = ctx.app_config
    if app_config is None:
        raise ValueError("App settings are not initialized")
    run_id = ctx.run_id

    try:
        cache_roles = ctx.container.cache.roles()
        cache_dsl_bundle = ctx.container.cache_dsl()
        unsupported_result = ensure_supported_cache_dataset(cache_roles.cache_admin, opts.dataset)
        if unsupported_result is not None:
            return unsupported_result

        build_result = ctx.container.target.runtime()
        runtime = build_result.runtime
        target_meta = runtime.meta()
        endpoint = target_meta.endpoint
        reader = runtime.reader
        report.set_context("target_runtime", _runtime_context(build_result))

        adapters = build_sync_adapters(cache_dsl_bundle)
        identity_keys, identity_id_fields = build_identity_index_plan()
        identity_syncer = IdentityIndexSyncer(
            runtime=cache_roles.cache_refresh,
            identity_keys=identity_keys,
            identity_id_fields=identity_id_fields,
        )
        runtime_policy = cache_dsl_bundle.runtime.policy
        cache_refresh = CacheRefreshUseCase(
            reader,
            cache_roles.cache_refresh,
            adapters,
            identity_syncer=identity_syncer,
            dependency_graph=cache_dsl_bundle.runtime.dependency_graph,
            schema_hashes=cache_dsl_bundle.runtime.schema_hashes,
            drift_mode=runtime_policy.drift_mode,
            drift_on_hash_mismatch=runtime_policy.drift_on_hash_mismatch,
            drift_rebuild_scope=runtime_policy.drift_rebuild_scope,
        )
        service = CacheCommandService(cache_roles.cache_admin, cache_refresh)
        return service.refresh(
            page_size=opts.page_size or app_config.refresh.page_size,
            max_pages=opts.max_pages or app_config.refresh.max_pages,
            logger=ctx.logger,
            report=report,
            run_id=run_id,
            include_deleted=opts.include_deleted,
            include_dependencies=(
                opts.include_dependencies
                if opts.include_dependencies is not None
                else runtime_policy.refresh_with_deps_default
            ),
            report_items_limit=(
                opts.report_items_limit or app_config.observability.report_items_limit
            ),
            api_base_url=endpoint,
            retries=opts.retries or app_config.api.retries,
            retry_backoff_seconds=opts.retry_backoff_seconds or app_config.api.retry_backoff_seconds,
            dataset=opts.dataset,
            catalog=ctx.catalog,
        )
    except ValueError as exc:
        typer.echo(f"ERROR: {exc}", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)
    except Exception as exc:
        logEvent(ctx.logger, logging.ERROR, run_id, "cache", f"Cache refresh failed: {exc}")
        typer.echo("ERROR: cache refresh failed (see logs/report)", err=True)
        return result_with(SystemErrorCode.INTERNAL_ERROR)


__all__ = ["handler", "Options"]
