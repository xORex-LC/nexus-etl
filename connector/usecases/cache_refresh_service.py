from __future__ import annotations

import logging
import time
import hashlib
from typing import Any

from connector.common.time import getNowIso
from connector.datasets.cache_sync import CacheSyncAdapterProtocol
from connector.domain.models import DiagnosticStage, ValidationErrorItem
from connector.domain.planning.identity_keys import format_identity_key
from connector.domain.ports.cache_repository import CacheRepositoryProtocol, UpsertResult
from connector.domain.ports.identity_repository import IdentityRepository
from connector.domain.ports.target_read import TargetPagedReaderProtocol
from connector.infra.logging.setup import logEvent


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
        identity_repo: IdentityRepository | None = None,
        identity_keys: dict[str, set[str]] | None = None,
        identity_id_fields: dict[str, str] | None = None,
    ):
        self.target_reader = target_reader
        self.cache_repo = cache_repo
        self.adapters = adapters
        self.identity_repo = identity_repo
        self.identity_keys = identity_keys or {}
        self.identity_id_fields = identity_id_fields or {}

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
                                        report.add_item(
                                            status="SKIPPED",
                                            row_ref=None,
                                            payload=None,
                                            errors=[],
                                            warnings=[],
                                            meta={
                                                "dataset": adapter.dataset,
                                                "key": key,
                                            },
                                            store=True,
                                        )
                                        continue

                                mapped = adapter.map_target_to_cache(raw)
                                result = self.cache_repo.upsert(adapter.dataset, mapped)
                                if result == UpsertResult.INSERTED:
                                    stats["inserted"] += 1
                                else:
                                    stats["updated"] += 1
                                self._update_identity_index(adapter.dataset, mapped)
                                report.add_item(
                                    status="OK",
                                    row_ref=None,
                                    payload=None,
                                    errors=[],
                                    warnings=[],
                                    meta={
                                        "dataset": adapter.dataset,
                                        "key": key,
                                        "result": result.value,
                                    },
                                    store=False,
                                )
                            except Exception as exc:
                                stats["failed"] += 1
                                logEvent(logger, logging.ERROR, run_id, "cache", f"Failed to upsert {key}: {exc}")
                                report.add_item(
                                    status="FAILED",
                                    row_ref=None,
                                    payload=None,
                                    errors=[
                                        ValidationErrorItem(
                                            stage=DiagnosticStage.CACHE,
                                            code="CACHE_ERROR",
                                            field=None,
                                            message=str(exc),
                                        )
                                    ],
                                    warnings=[],
                                    meta={
                                        "dataset": adapter.dataset,
                                        "key": key,
                                    },
                                    store=True,
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

        retries_used = 0
        if hasattr(self.target_reader, "client") and hasattr(self.target_reader.client, "getRetryAttempts"):
            retries_used = self.target_reader.client.getRetryAttempts() or 0
        totals = _sum_stats(stats_by_dataset)
        target_id = None
        if api_base_url:
            target_id = hashlib.sha256(api_base_url.encode("utf-8")).hexdigest()

        report.set_context(
            "cache_refresh",
            {
                "target_id": target_id,
                "target_type": "http" if api_base_url else None,
                "page_size": page_size,
                "max_pages": max_pages,
                "retries": retries,
                "retry_backoff_seconds": retry_backoff_seconds,
                "include_deleted": include_deleted,
                "retries_used": retries_used,
                "by_dataset": stats_by_dataset,
                "total": totals,
                "error_stats": error_stats,
            },
        )

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

    def _update_identity_index(self, dataset: str, mapped: dict[str, Any]) -> None:
        if self.identity_repo is None:
            return
        key_names = self.identity_keys.get(dataset)
        if not key_names:
            return
        id_field = self.identity_id_fields.get(dataset, "_id")
        resolved_id = mapped.get(id_field)
        if resolved_id is None:
            return
        resolved_id_str = str(resolved_id).strip()
        if resolved_id_str == "":
            return
        for key_name in key_names:
            value = mapped.get(key_name)
            if value is None:
                continue
            value_str = str(value).strip()
            if value_str == "":
                continue
            identity_key = format_identity_key(key_name, value_str)
            self.identity_repo.upsert_identity(dataset, identity_key, resolved_id_str)


def _sum_stats(stats_by_dataset: dict[str, dict[str, int]]) -> dict[str, int]:
    totals = {"inserted": 0, "updated": 0, "failed": 0, "skipped": 0}
    for stats in stats_by_dataset.values():
        totals["inserted"] += int(stats.get("inserted", 0))
        totals["updated"] += int(stats.get("updated", 0))
        totals["failed"] += int(stats.get("failed", 0))
        totals["skipped"] += int(stats.get("skipped", 0))
    return totals
