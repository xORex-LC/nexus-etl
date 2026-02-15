from __future__ import annotations

import logging
from dataclasses import dataclass

import typer

from connector.delivery.cli.context import CommandContext
from connector.delivery.commands.common import ensure_supported_cache_dataset, result_with
from connector.delivery.cli.bootstrap import (
    build_api_client,
    build_target_runtime,
    open_cache,
)
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.datasets.registry import build_identity_index_plan
from connector.infra.cache.dsl_runtime import build_sync_adapters
from connector.infra.logging.setup import logEvent
from connector.usecases.cache_command_service import CacheCommandService
from connector.usecases.cache_refresh_service import CacheRefreshUseCase


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


def _extract_transport(client: object) -> object | None:
    http_client = getattr(client, "client", None)
    return getattr(http_client, "_transport", None)


def _close_http_client(client: object) -> None:
    http_client = getattr(client, "client", None)
    close = getattr(http_client, "close", None)
    if callable(close):
        close()


def handler(ctx: CommandContext, opts: Options, report) -> CommandResult:
    app_settings = ctx.app_settings
    if app_settings is None:
        raise ValueError("App settings are not initialized")
    run_id = ctx.run_id

    try:
        with open_cache(app_settings.paths) as (_gateway, cache_roles, cache_dsl_bundle):
            unsupported_result = ensure_supported_cache_dataset(cache_roles.cache_admin, opts.dataset)
            if unsupported_result is not None:
                return unsupported_result

            runtime_transport = opts.api_transport
            if runtime_transport is None:
                legacy_client = build_api_client(app_settings.api, transport=opts.api_transport)
                runtime_transport = _extract_transport(legacy_client)
                _close_http_client(legacy_client)

            runtime = build_target_runtime(app_settings.api, transport=runtime_transport)
            target_meta = runtime.meta()
            base_url = target_meta.base_url
            reader = runtime.reader

            adapters = build_sync_adapters(cache_dsl_bundle)
            identity_keys, identity_id_fields = build_identity_index_plan()
            runtime_policy = cache_dsl_bundle.runtime.policy
            cache_refresh = CacheRefreshUseCase(
                reader,
                cache_roles.cache_refresh,
                adapters,
                identity_keys=identity_keys,
                identity_id_fields=identity_id_fields,
                dependency_graph=cache_dsl_bundle.runtime.dependency_graph,
                schema_hashes=cache_dsl_bundle.runtime.schema_hashes,
                drift_mode=runtime_policy.drift_mode,
                drift_on_hash_mismatch=runtime_policy.drift_on_hash_mismatch,
                drift_rebuild_scope=runtime_policy.drift_rebuild_scope,
            )
            service = CacheCommandService(cache_roles.cache_admin, cache_refresh)

            return service.refresh(
                page_size=opts.page_size or app_settings.refresh.page_size,
                max_pages=opts.max_pages or app_settings.refresh.max_pages,
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
                    opts.report_items_limit or app_settings.observability.report_items_limit
                ),
                api_base_url=base_url,
                retries=opts.retries or app_settings.api.retries,
                retry_backoff_seconds=opts.retry_backoff_seconds or app_settings.api.retry_backoff_seconds,
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
