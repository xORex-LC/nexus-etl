from __future__ import annotations

from connector.domain.cache_core import CacheClearPlanner, CacheDependencyGraph
from connector.domain.ports.cache.roles import CacheAdminPort


class CacheClearUseCase:
    """
    Назначение/ответственность:
        Очистка кэша (по датасету или полностью).
    """

    def __init__(
        self,
        cache_admin: CacheAdminPort,
        clear_planner: CacheClearPlanner | None = None,
    ):
        self.cache_admin = cache_admin
        self._clear_planner = clear_planner

    def clear(self, dataset: str | None = None) -> dict[str, int]:
        return self.clear_with_options(dataset=dataset, cascade=False)

    def clear_with_options(
        self,
        *,
        dataset: str | None = None,
        cascade: bool = False,
    ) -> dict[str, int]:
        available_datasets = self.cache_admin.list_datasets()
        planner = self._clear_planner or CacheClearPlanner(CacheDependencyGraph(available_datasets))
        clear_plan = planner.plan(dataset=dataset, cascade=cascade)
        targets = list(clear_plan.datasets)

        deleted: dict[str, int] = {}
        with self.cache_admin.transaction():
            for name in targets:
                deleted[name] = self.cache_admin.count(name)
                self.cache_admin.clear(name)
                self.cache_admin.reset_meta(name)

        return deleted
