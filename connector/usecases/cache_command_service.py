from __future__ import annotations

import logging

from connector.usecases.cache_refresh_service import CacheRefreshUseCase
from connector.usecases.ports import CacheCommandServiceProtocol
from connector.infra.logging.setup import logEvent


class CacheCommandService(CacheCommandServiceProtocol):
    """
    Оркестратор cache-команд (refresh/status/clear).
    """

    def __init__(self, cache_repo, cache_refresh: CacheRefreshUseCase | None = None):
        self.cache_repo = cache_repo
        self.cache_refresh = cache_refresh

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
        )

        failed = summary["users_failed"] + summary["orgs_failed"]
        report.summary.created = summary["users_inserted"] + summary["orgs_inserted"]
        report.summary.updated = summary["users_updated"] + summary["orgs_updated"]
        report.summary.failed = failed
        if "users_skipped_deleted" in summary:
            report.summary.skipped = summary["users_skipped_deleted"]
        return 0 if failed == 0 else 1

    def status(self, logger, report, run_id: str) -> tuple[int, dict]:
        try:
            status = self._get_cache_status()
            report.items.append({"status": status})
            return 0, status
        except Exception as exc:
            logEvent(logger, logging.ERROR, run_id, "cache", f"Cache status failed: {exc}")
            return 2, {}

    def clear(self, logger, report, run_id: str) -> tuple[int, dict]:
        try:
            cleared = self._clear_cache()
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

    def _get_cache_status(self) -> dict:
        """
        Возвращает состояние кэша: counts, last refresh, schema_version.
        """
        self.cache_repo.ensure_schema()
        users_count, org_count = self.cache_repo.get_counts()
        status = {
            "schema_version": self.cache_repo.get_meta("schema_version"),
            "users_count": users_count,
            "org_count": org_count,
            "users_last_refresh_at": self.cache_repo.get_meta("users_last_refresh_at"),
            "org_last_refresh_at": self.cache_repo.get_meta("org_last_refresh_at"),
            "source_api_base": self.cache_repo.get_meta("source_api_base"),
        }

        status["meta_users_count"] = _safe_int(self.cache_repo.get_meta("users_count"))
        status["meta_org_count"] = _safe_int(self.cache_repo.get_meta("org_count"))
        return status

    def _clear_cache(self) -> dict[str, int]:
        """
        Очищает таблицы users/organizations и сбрасывает meta счётчики.
        """
        self.cache_repo.ensure_schema()
        self.cache_repo.begin()
        try:
            users_deleted = self.cache_repo.clear_users()
            orgs_deleted = self.cache_repo.clear_orgs()

            self.cache_repo.set_meta("users_count", "0")
            self.cache_repo.set_meta("org_count", "0")
            self.cache_repo.set_meta("users_last_refresh_at", None)
            self.cache_repo.set_meta("org_last_refresh_at", None)
            self.cache_repo.set_meta("source_api_base", None)

            self.cache_repo.commit()
            return {"users_deleted": users_deleted, "orgs_deleted": orgs_deleted}
        except Exception:
            self.cache_repo.rollback()
            raise


def _safe_int(value: str | None) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


__all__ = ["CacheCommandService"]
