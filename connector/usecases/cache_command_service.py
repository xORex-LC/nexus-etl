from __future__ import annotations

import logging

from connector.usecases.cache_refresh_service import CacheRefreshUseCase
from connector.usecases.cache_status_usecase import CacheStatusUseCase
from connector.usecases.cache_clear_usecase import CacheClearUseCase
from connector.usecases.ports import CacheCommandServiceProtocol
from connector.infra.logging.setup import logEvent


class CacheCommandService(CacheCommandServiceProtocol):
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
        report.summary.created = int(total.get("inserted", 0))
        report.summary.updated = int(total.get("updated", 0))
        report.summary.failed = int(total.get("failed", 0))
        report.summary.skipped = int(total.get("skipped", 0))
        report.summary.by_dataset = summary.get("by_dataset", {})
        return 0 if report.summary.failed == 0 else 1

    def status(self, logger, report, run_id: str, dataset: str | None = None) -> tuple[int, dict]:
        try:
            status = self.cache_status.status(dataset=dataset)
            report.items.append({"status": status})
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
            report.items.append({"cleared": cleared})
            report.summary.failed = 0
            report.summary.created = 0
            report.summary.updated = 0
            return 0, cleared
        except Exception as exc:
            logEvent(logger, logging.ERROR, run_id, "cache", f"Cache clear failed: {exc}")
            return 2, {}


__all__ = ["CacheCommandService"]
