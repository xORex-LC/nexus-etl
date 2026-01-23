from __future__ import annotations

import logging
import time
from typing import Any

from connector.common.time import getNowIso
from connector.datasets.cache_sync import CacheSyncAdapterProtocol
from connector.domain.ports.cache_repo import CacheRepositoryProtocol
from connector.domain.ports.target_read import TargetPagedReaderProtocol
from connector.infra.logging.setup import logEvent


def _append_item(report, dataset: str, entity_type: str, key: str, status: str, error: str | None = None) -> dict:
    item = {
        "dataset": dataset,
        "entity_type": entity_type,
        "key": key,
        "status": status,
        "errors": [] if error is None else [{"code": "CACHE_ERROR", "field": None, "message": error}],
        "warnings": [],
    }
    report.items.append(item)
    return item


def _append_item_limited(
    report,
    dataset: str,
    entity_type: str,
    key: str,
    status: str,
    error: str | None,
    report_items_limit: int,
) -> None:
    # Always keep failed/skipped until limit; success не сохраняем.
    if status not in ("failed", "skipped"):
        return
    if len(report.items) >= report_items_limit:
        try:
            report.meta.items_truncated = True
        except Exception:
            pass
        return
    _append_item(report, dataset, entity_type, key, status, error)


class CacheRefreshUseCase:
    """
    Назначение/ответственность:
        Обновление кэша из целевой системы через порты read/repo.
    Взаимодействия:
        - TargetPagedReaderProtocol для чтения страниц.
        - CacheRepositoryProtocol для записи в кэш.
        - CacheSyncAdapterProtocol для маппинга и upsert.
    """

    def __init__(
        self,
        target_reader: TargetPagedReaderProtocol,
        cache_repo: CacheRepositoryProtocol,
        adapters: list[CacheSyncAdapterProtocol],
    ):
        self.target_reader = target_reader
        self.cache_repo = cache_repo
        self.adapters = adapters

    def refresh(
        self,
        page_size: int,
        max_pages: int | None,
        logger,
        report,
        run_id: str,
        include_deleted: bool = False,
        report_items_limit: int = 200,
        api_base_url: str | None = None,
        retries: int | None = None,
        retry_backoff_seconds: float | None = None,
    ) -> dict[str, Any]:
        """
        Обновляет кэш из целевой системы с пагинацией.
        """
        self.cache_repo.ensure_schema()
        logEvent(
            logger,
            logging.INFO,
            run_id,
            "cache",
            f"cache-refresh start page_size={page_size} max_pages={max_pages} include_deleted={include_deleted}",
        )
        start_monotonic = time.monotonic()

        inserted_users = updated_users = failed_users = skipped_deleted_users = 0
        deleted_included_users = 0
        inserted_orgs = updated_orgs = failed_orgs = 0
        pages_users = pages_orgs = 0
        error_stats: dict[str, int] = {}

        try:
            self.cache_repo.begin()

            for adapter in self.adapters:
                for page_result in self.target_reader.iter_pages(adapter.list_path, page_size, max_pages):
                    if not page_result.ok:
                        code = page_result.error_code.name if page_result.error_code else "API_ERROR"
                        error_stats[code] = error_stats.get(code, 0) + 1
                        raise RuntimeError(page_result.error_message or "Target read failed")

                    if adapter.report_entity == "user":
                        pages_users = max(pages_users, page_result.page)
                    if adapter.report_entity == "org":
                        pages_orgs = max(pages_orgs, page_result.page)

                    items = page_result.items or []
                    logEvent(
                        logger,
                        logging.DEBUG,
                        run_id,
                        "api",
                        f"GET {adapter.report_entity} page={page_result.page} rows={page_size} items={len(items)}",
                    )
                    for raw in items:
                        key = adapter.get_item_key(raw)
                        try:
                            if adapter.is_deleted(raw):
                                if include_deleted:
                                    deleted_included_users += 1
                                else:
                                    skipped_deleted_users += 1
                                    _append_item_limited(
                                        report,
                                        adapter.dataset,
                                        adapter.report_entity,
                                        key,
                                        "skipped",
                                        None,
                                        report_items_limit,
                                    )
                                    continue

                            mapped = adapter.map_target_to_cache(raw)
                            status = adapter.upsert(self.cache_repo, mapped)
                            if adapter.report_entity == "user":
                                if status == "inserted":
                                    inserted_users += 1
                                else:
                                    updated_users += 1
                            if adapter.report_entity == "org":
                                if status == "inserted":
                                    inserted_orgs += 1
                                else:
                                    updated_orgs += 1
                            _append_item_limited(
                                report,
                                adapter.dataset,
                                adapter.report_entity,
                                key,
                                status,
                                None,
                                report_items_limit,
                            )
                        except Exception as exc:
                            if adapter.report_entity == "user":
                                failed_users += 1
                            if adapter.report_entity == "org":
                                failed_orgs += 1
                            logEvent(logger, logging.ERROR, run_id, "cache", f"Failed to upsert {key}: {exc}")
                            _append_item(
                                report,
                                adapter.dataset,
                                adapter.report_entity,
                                key,
                                "failed",
                                str(exc),
                            )

            users_count, org_count = self.cache_repo.get_counts()
            now_iso = getNowIso()

            self.cache_repo.set_meta("users_count", str(users_count))
            self.cache_repo.set_meta("org_count", str(org_count))
            self.cache_repo.set_meta("users_last_refresh_at", now_iso)
            self.cache_repo.set_meta("org_last_refresh_at", now_iso)
            if api_base_url:
                self.cache_repo.set_meta("source_api_base", api_base_url)

            self.cache_repo.commit()
        except Exception as exc:
            self.cache_repo.rollback()
            logEvent(logger, logging.ERROR, run_id, "cache", f"Cache refresh failed: {exc}")
            raise

        report.meta.pages_users = pages_users or None
        report.meta.pages_orgs = pages_orgs or None
        report.meta.api_base_url = api_base_url
        report.meta.page_size = page_size
        report.meta.max_pages = max_pages
        report.meta.retries = retries
        report.meta.retry_backoff_seconds = retry_backoff_seconds
        report.meta.include_deleted = include_deleted
        report.meta.skipped_deleted_users = deleted_included_users if include_deleted else skipped_deleted_users

        retries_used = 0
        if hasattr(self.target_reader, "client") and hasattr(self.target_reader.client, "getRetryAttempts"):
            retries_used = self.target_reader.client.getRetryAttempts() or 0
        report.meta.retries_used = retries_used

        report.summary.created = inserted_users + inserted_orgs
        report.summary.updated = updated_users + updated_orgs
        report.summary.failed = failed_users + failed_orgs
        report.summary.error_stats = error_stats
        report.summary.skipped = skipped_deleted_users
        report.summary.retries_total = retries_used

        duration_ms = int((time.monotonic() - start_monotonic) * 1000)
        logEvent(
            logger,
            logging.INFO,
            run_id,
            "cache",
            f"cache-refresh done users_count={users_count} org_count={org_count} duration_ms={duration_ms}",
        )

        return {
            "users_inserted": inserted_users,
            "users_updated": updated_users,
            "users_failed": failed_users,
            "users_skipped_deleted": skipped_deleted_users,
            "orgs_inserted": inserted_orgs,
            "orgs_updated": updated_orgs,
            "orgs_failed": failed_orgs,
            "users_count": users_count,
            "org_count": org_count,
            "pages_users": pages_users,
            "pages_orgs": pages_orgs,
        }
