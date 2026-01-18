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
        include_deleted_users: bool,
        logger,
        run_id: str,
        report,
        report_items_limit: int,
        report_items_success: bool,
        report_dir: str,
    ) -> int: ...

@runtime_checkable
class CacheCommandServiceProtocol(Protocol):
    """
    Назначение:
        Контракт для сервисов работы с кэшем (refresh/status/clear).
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
    ) -> int: ...

    def status(self, conn, logger, report, run_id: str) -> tuple[int, dict]: ...
    def clear(self, conn, logger, report, run_id: str) -> tuple[int, dict]: ...

__all__ = ["ImportPlanServiceProtocol", "CacheCommandServiceProtocol"]
