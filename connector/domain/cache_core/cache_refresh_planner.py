"""
Назначение:
    Построение refresh-плана для cache.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.cache_core.cache_dependency_graph import CacheDependencyGraph


@dataclass(frozen=True)
class CacheRefreshPlan:
    datasets: tuple[str, ...]


class CacheRefreshPlanner:
    """
    Чистый planner refresh scope/order.
    """

    def __init__(self, graph: CacheDependencyGraph) -> None:
        self._graph = graph

    def plan(self, dataset: str | None = None) -> CacheRefreshPlan:
        # Поведение по умолчанию сохраняет текущий runtime:
        # явный dataset не расширяем зависимостями автоматически.
        datasets = tuple(self._graph.refresh_order(dataset=dataset, include_dependencies=False))
        return CacheRefreshPlan(datasets=datasets)
