from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ApiClientProtocol(Protocol):
    def getJson(self, path: str, params: dict[str, Any] | None = None) -> Any: ...
    def getPagedItems(self, path: str, pageSize: int, maxPages: int) -> Any: ...


@runtime_checkable
class ImportPlanServiceProtocol(Protocol):
    def run(
        self,
        conn,
        csv_path: str,
        csv_has_header: bool,
        include_deleted_users: bool,
        on_missing_org: str,
        logger,
        run_id: str,
        report,
        report_items_limit: int,
        report_items_success: bool,
        report_dir: str,
    ) -> int: ...


@runtime_checkable
class CacheCommandServiceProtocol(Protocol):
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


@runtime_checkable
class UserApiProtocol(Protocol):
    def upsertUser(self, resourceId: str, payload: dict[str, Any]) -> tuple[int, Any]: ...


__all__ = [
    "ApiClientProtocol",
    "ImportPlanServiceProtocol",
    "CacheCommandServiceProtocol",
    "UserApiProtocol",
]
