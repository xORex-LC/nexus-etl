from __future__ import annotations

from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.cache.roles import CacheAdminPort
from connector.domain.reporting.contracts import ReportContextKey, ReportOpKey
from connector.domain.reporting.events import AddOpEvent, SetContextEvent

from connector.usecases.cache_refresh_service import CacheRefreshUseCase
from connector.usecases.cache_status_usecase import CacheStatusUseCase
from connector.usecases.cache_clear_usecase import CacheClearUseCase


class CacheCommandService:
    """
    Оркестратор cache-команд (refresh/status/clear).
    """

    def __init__(
        self,
        cache_admin: CacheAdminPort,
        cache_refresh: CacheRefreshUseCase | None = None,
        cache_status: CacheStatusUseCase | None = None,
        cache_clear: CacheClearUseCase | None = None,
    ):
        self.cache_admin = cache_admin
        self.cache_refresh = cache_refresh
        self.cache_status = cache_status or CacheStatusUseCase(cache_admin)
        self.cache_clear = cache_clear

    def refresh(
        self,
        page_size: int,
        max_pages: int,
        logger,
        report_sink,
        run_id: str,
        include_deleted: bool | None = None,
        include_dependencies: bool = False,
        report_items_limit: int = 200,
        api_base_url: str | None = None,
        retries: int | None = None,
        retry_backoff_seconds: float | None = None,
        dataset: str | None = None,
        catalog: ErrorCatalog | None = None,
    ) -> CommandResult:
        if self.cache_refresh is None:
            raise ValueError("Cache refresh usecase is not configured")
        summary = self.cache_refresh.refresh(
            page_size=page_size,
            max_pages=max_pages,
            logger=logger,
            report_sink=report_sink,
            run_id=run_id,
            include_deleted=include_deleted,
            include_dependencies=include_dependencies,
            report_items_limit=report_items_limit,
            api_base_url=api_base_url,
            retries=retries,
            retry_backoff_seconds=retry_backoff_seconds,
            dataset=dataset,
            catalog=catalog,
        )

        total = summary.get("total", {})
        failed = int(total.get("failed", 0))
        report_sink.emit(
            AddOpEvent(
                name=ReportOpKey.CACHE_REFRESH,
                ok=int(total.get("inserted", 0)) + int(total.get("updated", 0)),
                failed=failed,
                count=sum(total.values()),
            )
        )

        result = CommandResult(summary=summary)
        if failed:
            result.add_code(SystemErrorCode.DATA_INVALID)
        return result

    def status(
        self, logger, report_sink, run_id: str, dataset: str | None = None
    ) -> CommandResult:
        try:
            status = self.cache_status.status(dataset=dataset)
            report_sink.emit(
                SetContextEvent(
                    name=ReportContextKey.CACHE_STATUS, value={"status": status}
                )
            )
            return CommandResult(summary=status)
        except Exception as exc:
            logger.error(
                "Cache status failed",
                scope="cache",
                dataset=dataset,
                error=str(exc),
                error_type=exc.__class__.__name__,
            )
            result = CommandResult(summary={})
            result.add_code(SystemErrorCode.CACHE_ERROR)
            return result

    def clear(
        self,
        logger,
        report_sink,
        run_id: str,
        dataset: str | None = None,
        *,
        cascade: bool = False,
    ) -> CommandResult:
        try:
            if self.cache_clear is None:
                raise ValueError("Cache clear usecase is not configured")
            cleared = self.cache_clear.clear_with_options(
                dataset=dataset, cascade=cascade
            )
            logger.info(
                "Cache clear completed",
                scope="cache",
                dataset=dataset,
                cascade=cascade,
                cleared=cleared,
            )
            report_sink.emit(
                SetContextEvent(
                    name=ReportContextKey.CACHE_CLEAR, value={"cleared": cleared}
                )
            )
            return CommandResult(summary=cleared)
        except Exception as exc:
            logger.error(
                "Cache clear failed",
                scope="cache",
                dataset=dataset,
                cascade=cascade,
                error=str(exc),
                error_type=exc.__class__.__name__,
            )
            result = CommandResult(summary={})
            result.add_code(SystemErrorCode.CACHE_ERROR)
            return result


__all__ = ["CacheCommandService"]
