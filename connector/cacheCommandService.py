from __future__ import annotations

import logging

from .cacheService import clearCache, getCacheStatus, refreshCacheFromApi
from .protocols_services import CacheCommandServiceProtocol
from .loggingSetup import logEvent


class CacheCommandService(CacheCommandServiceProtocol):
    """
    Оркестратор cache-команд (refresh/status/clear).
    """

    def refresh(
        self,
        conn,
        settings,
        page_size: int,
        max_pages: int,
        timeout_seconds: float,
        retries: int,
        retry_backoff_seconds: float,
        logger,
        report,
        run_id: str,
        api_transport=None,
        include_deleted_users: bool = False,
        report_items_limit: int = 200,
        report_items_success: bool = False,
    ) -> int:
        summary = refreshCacheFromApi(
            conn=conn,
            settings=settings,
            pageSize=page_size,
            maxPages=max_pages,
            timeoutSeconds=timeout_seconds,
            retries=retries,
            retryBackoffSeconds=retry_backoff_seconds,
            logger=logger,
            report=report,
            transport=api_transport,
            includeDeletedUsers=include_deleted_users,
            reportItemsLimit=report_items_limit,
            reportItemsSuccess=report_items_success,
        )

        failed = summary["users_failed"] + summary["orgs_failed"]
        report.summary.created = summary["users_inserted"] + summary["orgs_inserted"]
        report.summary.updated = summary["users_updated"] + summary["orgs_updated"]
        report.summary.failed = failed
        if "users_skipped_deleted" in summary:
            report.summary.skipped = summary["users_skipped_deleted"]
        return 0 if failed == 0 else 1

    def status(self, conn, logger, report, run_id: str) -> tuple[int, dict]:
        try:
            status = getCacheStatus(conn)
            report.items.append({"status": status})
            return 0, status
        except Exception as exc:
            logEvent(logger, logging.ERROR, run_id, "cache", f"Cache status failed: {exc}")
            return 2, {}

    def clear(self, conn, logger, report, run_id: str) -> tuple[int, dict]:
        try:
            cleared = clearCache(conn)
            logEvent(
                logger,
                logging.INFO,
                run_id,
                "cache",
                f"cache clear: users={cleared.get('users_deleted')} orgs={cleared.get('orgs_deleted')}",
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
