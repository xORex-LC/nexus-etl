"""
Назначение:
    Построение clear-плана для cache.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.cache_core.cache_dependency_graph import CacheDependencyGraph


@dataclass(frozen=True)
class CacheClearPlan:
    datasets: tuple[str, ...]


class CacheClearPlanner:
    """
    Чистый planner clear scope/order.
    """

    def __init__(self, graph: CacheDependencyGraph) -> None:
        self._graph = graph

    def plan(self, dataset: str | None = None, *, cascade: bool = False) -> CacheClearPlan:
        datasets = tuple(self._graph.clear_order(dataset=dataset, cascade=cascade))
        return CacheClearPlan(datasets=datasets)
