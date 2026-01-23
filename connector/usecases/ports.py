from __future__ import annotations

from typing import Protocol, runtime_checkable

@runtime_checkable
class ImportPlanServiceProtocol(Protocol):
    """
    Назначение:
        Контракт для сервиса построения плана импорта.
    """

    def run(
        self,
        conn,
        csv_path: str,
        csv_has_header: bool,
        include_deleted: bool,
        dataset: str,
        logger,
        run_id: str,
        report,
        report_items_limit: int,
        include_skipped_in_report: bool,
        report_dir: str,
        settings=None,
    ) -> int: ...

@runtime_checkable
class CacheCommandServiceProtocol(Protocol):
    """
    Назначение:
        Контракт для сервисов работы с кэшем (refresh/status/clear).
    """

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
    ) -> int: ...

    def status(self, logger, report, run_id: str, dataset: str | None = None) -> tuple[int, dict]: ...
    def clear(self, logger, report, run_id: str, dataset: str | None = None) -> tuple[int, dict]: ...

__all__ = ["ImportPlanServiceProtocol", "CacheCommandServiceProtocol"]
