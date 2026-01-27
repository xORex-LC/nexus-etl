from __future__ import annotations

import logging

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
        cache_repo,
        cache_refresh: CacheRefreshUseCase | None = None,
        cache_status: CacheStatusUseCase | None = None,
        cache_clear: CacheClearUseCase | None = None,
    ):
        self.cache_repo = cache_repo
        self.cache_refresh = cache_refresh
        self.cache_status = cache_status or CacheStatusUseCase(cache_repo)
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
    ) -> int:
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
        )

        total = summary.get("total", {})
        failed = int(total.get("failed", 0))
        report.add_op("cache_refresh", ok=int(total.get("inserted", 0)) + int(total.get("updated", 0)), failed=failed, count=sum(total.values()))
        return 0 if failed == 0 else 1

    def status(self, logger, report, run_id: str, dataset: str | None = None) -> tuple[int, dict]:
        try:
            status = self.cache_status.status(dataset=dataset)
            report.set_meta(dataset=dataset)
            report.set_context("cache_status", {"status": status})
            return 0, status
        except Exception as exc:
            logEvent(logger, logging.ERROR, run_id, "cache", f"Cache status failed: {exc}")
            return 2, {}

    def clear(self, logger, report, run_id: str, dataset: str | None = None) -> tuple[int, dict]:
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
            return 0, cleared
        except Exception as exc:
            logEvent(logger, logging.ERROR, run_id, "cache", f"Cache clear failed: {exc}")
            return 2, {}


__all__ = ["CacheCommandService"]
