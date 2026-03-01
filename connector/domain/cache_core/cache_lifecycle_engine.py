"""
Назначение:
    CacheLifecycleEngine — единый command-level orchestration для refresh/status/clear.
"""

from __future__ import annotations

from typing import Any, Protocol

from connector.domain.cache_core.cache_clear_planner import CacheClearPlanner
from connector.domain.cache_core.cache_dependency_graph import CacheDependencyGraph
from connector.domain.cache_core.cache_status_evaluator import CacheDatasetSnapshot, CacheStatusEvaluator
from connector.domain.ports.cache.roles import CacheAdminPort

class CacheRefreshRunner(Protocol):
    """
    Назначение:
        Минимальный контракт refresh runner для lifecycle engine.
    """

    def refresh(self, **kwargs) -> dict[str, Any]: ...


class CacheLifecycleEngine:
    """
    Назначение:
        Единая точка orchestration cache-сценариев на уровне команды.

    Контракт:
        - refresh делегируется в CacheRefreshUseCase (I/O-heavy pipeline).
        - status/clear выполняются здесь через чистые planners/evaluator.
    """

    def __init__(
        self,
        *,
        cache_admin: CacheAdminPort,
        refresh_usecase: CacheRefreshRunner | None = None,
        status_evaluator: CacheStatusEvaluator | None = None,
        clear_planner: CacheClearPlanner | None = None,
    ) -> None:
        self.cache_admin = cache_admin
        self.refresh_usecase = refresh_usecase
        self._status_evaluator = status_evaluator or CacheStatusEvaluator()
        self._clear_planner = clear_planner

    def refresh(
        self,
        *,
        page_size: int,
        max_pages: int | None,
        logger,
        report_sink,
        run_id: str,
        catalog,
        include_deleted: bool | None = None,
        include_dependencies: bool = False,
        report_items_limit: int = 200,
        api_base_url: str | None = None,
        retries: int | None = None,
        retry_backoff_seconds: float | None = None,
        dataset: str | None = None,
    ) -> dict[str, Any]:
        if self.refresh_usecase is None:
            raise ValueError("Cache refresh usecase is not configured")
        return self.refresh_usecase.refresh(
            page_size=page_size,
            max_pages=max_pages,
            logger=logger,
            report_sink=report_sink,
            run_id=run_id,
            catalog=catalog,
            include_deleted=include_deleted,
            include_dependencies=include_dependencies,
            report_items_limit=report_items_limit,
            api_base_url=api_base_url,
            retries=retries,
            retry_backoff_seconds=retry_backoff_seconds,
            dataset=dataset,
        )

    def status(self, *, dataset: str | None = None) -> dict:
        global_meta = self.cache_admin.get_meta(None).values
        snapshots = [
            CacheDatasetSnapshot(
                dataset=name,
                counts=self.cache_admin.count_by_table(name),
                meta=self.cache_admin.get_meta(name).values,
            )
            for name in self.cache_admin.list_datasets()
        ]
        return self._status_evaluator.evaluate(
            schema_version=global_meta.get("schema_version"),
            global_meta=global_meta,
            snapshots=snapshots,
            dataset=dataset,
        )

    def clear(
        self,
        *,
        dataset: str | None = None,
        cascade: bool = False,
    ) -> dict[str, int]:
        available_datasets = self.cache_admin.list_datasets()
        clear_planner = self._clear_planner or CacheClearPlanner(CacheDependencyGraph(available_datasets))
        clear_plan = clear_planner.plan(dataset=dataset, cascade=cascade)
        targets = list(clear_plan.datasets)

        deleted: dict[str, int] = {}
        with self.cache_admin.transaction():
            for name in targets:
                deleted[name] = self.cache_admin.count(name)
                self.cache_admin.clear(name)
                self.cache_admin.reset_meta(name)
        return deleted
