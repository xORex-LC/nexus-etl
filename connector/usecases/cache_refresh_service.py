from __future__ import annotations

import logging
import time
from typing import Any

from connector.common.time import getNowIso
from connector.datasets.cache_sync import CacheSyncAdapterProtocol
from connector.domain.ports.cache_repository import CacheRepositoryProtocol, UpsertResult
from connector.domain.ports.target_read import TargetPagedReaderProtocol
from connector.infra.logging.setup import logEvent


def _append_item(report, dataset: str, key: str, status: str, error: str | None = None) -> dict:
    item = {
        "dataset": dataset,
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
    _append_item(report, dataset, key, status, error)


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
        dataset: str | None = None,
    ) -> dict[str, Any]:
        """
        Обновляет кэш из целевой системы с пагинацией.
        """
        logEvent(
            logger,
            logging.INFO,
            run_id,
            "cache",
            f"cache-refresh start page_size={page_size} max_pages={max_pages} include_deleted={include_deleted}",
        )
        start_monotonic = time.monotonic()

        stats_by_dataset: dict[str, dict[str, int]] = {}
        error_stats: dict[str, int] = {}

        active_adapters = self.adapters
        if dataset is not None:
            active_adapters = [a for a in self.adapters if a.dataset == dataset]
            if not active_adapters:
                raise ValueError(f"Unsupported cache dataset: {dataset}")

        try:
            with self.cache_repo.transaction():
                for adapter in active_adapters:
                    stats = stats_by_dataset.setdefault(
                        adapter.dataset,
                        {
                            "inserted": 0,
                            "updated": 0,
                            "failed": 0,
                            "skipped": 0,
                            "pages": 0,
                        },
                    )
                    for page_result in self.target_reader.iter_pages(adapter.list_path, page_size, max_pages):
                        if not page_result.ok:
                            code = page_result.error_code.name if page_result.error_code else "API_ERROR"
                            error_stats[code] = error_stats.get(code, 0) + 1
                            raise RuntimeError(page_result.error_message or "Target read failed")

                        stats["pages"] = max(stats["pages"], page_result.page)

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
                                        pass
                                    else:
                                        stats["skipped"] += 1
                                        _append_item_limited(
                                            report,
                                            adapter.dataset,
                                            key,
                                            "skipped",
                                            None,
                                            report_items_limit,
                                        )
                                        continue

                                mapped = adapter.map_target_to_cache(raw)
                                result = self.cache_repo.upsert(adapter.dataset, mapped)
                                if result == UpsertResult.INSERTED:
                                    stats["inserted"] += 1
                                else:
                                    stats["updated"] += 1
                                _append_item_limited(
                                    report,
                                    adapter.dataset,
                                    key,
                                    result.value,
                                    None,
                                    report_items_limit,
                                )
                            except Exception as exc:
                                stats["failed"] += 1
                                logEvent(logger, logging.ERROR, run_id, "cache", f"Failed to upsert {key}: {exc}")
                                _append_item(
                                    report,
                                    adapter.dataset,
                                    key,
                                    "failed",
                                    str(exc),
                                )

                now_iso = getNowIso()

                for name in stats_by_dataset.keys():
                    count_total = self.cache_repo.count(name)
                    stats_by_dataset[name]["count_total"] = count_total
                    self.cache_repo.set_meta(name, "last_refresh_at", now_iso)
                    self.cache_repo.set_meta(name, "last_refresh_run_id", run_id)
                    self.cache_repo.set_meta(name, "last_refresh_pages", str(stats_by_dataset[name]["pages"]))
                    self.cache_repo.set_meta(
                        name,
                        "last_refresh_items",
                        str(
                            stats_by_dataset[name]["inserted"]
                            + stats_by_dataset[name]["updated"]
                            + stats_by_dataset[name]["failed"]
                            + stats_by_dataset[name]["skipped"]
                        ),
                    )
                    self.cache_repo.set_meta(name, "count_total", str(count_total))
                if api_base_url:
                    self.cache_repo.set_meta(None, "source_api_base", api_base_url)
        except Exception as exc:
            logEvent(logger, logging.ERROR, run_id, "cache", f"Cache refresh failed: {exc}")
            raise

        report.meta.api_base_url = api_base_url
        report.meta.page_size = page_size
        report.meta.max_pages = max_pages
        report.meta.retries = retries
        report.meta.retry_backoff_seconds = retry_backoff_seconds
        report.meta.include_deleted = include_deleted

        retries_used = 0
        if hasattr(self.target_reader, "client") and hasattr(self.target_reader.client, "getRetryAttempts"):
            retries_used = self.target_reader.client.getRetryAttempts() or 0
        report.meta.retries_used = retries_used

        totals = _sum_stats(stats_by_dataset)
        report.summary.created = totals["inserted"]
        report.summary.updated = totals["updated"]
        report.summary.failed = totals["failed"]
        report.summary.error_stats = error_stats
        report.summary.skipped = totals["skipped"]
        report.summary.retries_total = retries_used
        report.summary.by_dataset = stats_by_dataset

        duration_ms = int((time.monotonic() - start_monotonic) * 1000)
        logEvent(
            logger,
            logging.INFO,
            run_id,
            "cache",
            f"cache-refresh done datasets={len(stats_by_dataset)} duration_ms={duration_ms}",
        )

        return {
            "by_dataset": stats_by_dataset,
            "total": totals,
        }


def _sum_stats(stats_by_dataset: dict[str, dict[str, int]]) -> dict[str, int]:
    totals = {"inserted": 0, "updated": 0, "failed": 0, "skipped": 0}
    for stats in stats_by_dataset.values():
        totals["inserted"] += int(stats.get("inserted", 0))
        totals["updated"] += int(stats.get("updated", 0))
        totals["failed"] += int(stats.get("failed", 0))
        totals["skipped"] += int(stats.get("skipped", 0))
    return totals
