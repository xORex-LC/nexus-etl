from __future__ import annotations

import logging

from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.cache.roles import CacheAdminPort

from connector.usecases.cache_refresh_service import CacheRefreshUseCase
from connector.usecases.cache_status_usecase import CacheStatusUseCase
from connector.usecases.cache_clear_usecase import CacheClearUseCase
from connector.infra.logging.setup import logEvent


class CacheCommandService:
    """
    Оркестратор cache-команд (refresh/status/clear).
    """

    def __init__(
        self,
        cache_gateway: CacheAdminPort,
        cache_refresh: CacheRefreshUseCase | None = None,
        cache_status: CacheStatusUseCase | None = None,
        cache_clear: CacheClearUseCase | None = None,
    ):
        self.cache_gateway = cache_gateway
        self.cache_refresh = cache_refresh
        self.cache_status = cache_status or CacheStatusUseCase(cache_gateway)
        self.cache_clear = cache_clear

    def refresh(
        self,
        page_size: int,
        max_pages: int,
        logger,
        report,
        run_id: str,
        include_deleted: bool = False,
        report_items_limit: int = 200,
        api_base_url: str | None = None,
        retries: int | None = None,
        retry_backoff_seconds: float | None = None,
        dataset: str | None = None,
        catalog: ErrorCatalog | None = None,
    ) -> CommandResult:
        if self.cache_refresh is None:
            raise ValueError("Cache refresh usecase is not configured")
        report.set_meta(dataset=dataset, items_limit=report_items_limit)
        summary = self.cache_refresh.refresh(
            page_size=page_size,
            max_pages=max_pages,
            logger=logger,
            report=report,
            run_id=run_id,
            include_deleted=include_deleted,
            report_items_limit=report_items_limit,
            api_base_url=api_base_url,
            retries=retries,
            retry_backoff_seconds=retry_backoff_seconds,
            dataset=dataset,
            catalog=catalog,
        )

        total = summary.get("total", {})
        failed = int(total.get("failed", 0))
        report.add_op(
            "cache_refresh",
            ok=int(total.get("inserted", 0)) + int(total.get("updated", 0)),
            failed=failed,
            count=sum(total.values()),
        )

        result = CommandResult(summary=summary)
        if failed:
            result.add_code(SystemErrorCode.DATA_INVALID)
        return result

    def status(
        self, logger, report, run_id: str, dataset: str | None = None
    ) -> CommandResult:
        try:
            status = self.cache_status.status(dataset=dataset)
            report.set_meta(dataset=dataset)
            report.set_context("cache_status", {"status": status})
            return CommandResult(summary=status)
        except Exception as exc:
            logEvent(logger, logging.ERROR, run_id, "cache", f"Cache status failed: {exc}")
            result = CommandResult(summary={})
            result.add_code(SystemErrorCode.CACHE_ERROR)
            return result

    def clear(
        self, logger, report, run_id: str, dataset: str | None = None
    ) -> CommandResult:
        try:
            if self.cache_clear is None:
                raise ValueError("Cache clear usecase is not configured")
            cleared = self.cache_clear.clear(dataset=dataset)
            logEvent(
                logger,
                logging.INFO,
                run_id,
                "cache",
                f"cache clear: {cleared}",
            )
            report.set_meta(dataset=dataset)
            report.set_context("cache_clear", {"cleared": cleared})
            return CommandResult(summary=cleared)
        except Exception as exc:
            logEvent(logger, logging.ERROR, run_id, "cache", f"Cache clear failed: {exc}")
            result = CommandResult(summary={})
            result.add_code(SystemErrorCode.CACHE_ERROR)
            return result


__all__ = ["CacheCommandService"]
