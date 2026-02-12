from __future__ import annotations

from connector.domain.cache_core import CacheClearPlanner, CacheDependencyGraph, CacheRefreshPlanner


def test_refresh_planner_returns_all_datasets_in_refresh_order() -> None:
    planner = CacheRefreshPlanner(CacheDependencyGraph(("organizations", "employees")))
    plan = planner.plan()
    assert plan.datasets == ("organizations", "employees")


def test_clear_planner_returns_single_dataset_without_cascade() -> None:
    planner = CacheClearPlanner(
        CacheDependencyGraph(
            ("organizations", "employees"),
            dependencies={"employees": ("organizations",)},
        )
    )
    plan = planner.plan(dataset="organizations", cascade=False)
    assert plan.datasets == ("organizations",)


def test_clear_planner_returns_dependent_scope_when_cascade_enabled() -> None:
    planner = CacheClearPlanner(
        CacheDependencyGraph(
            ("organizations", "employees"),
            dependencies={"employees": ("organizations",)},
        )
    )
    plan = planner.plan(dataset="organizations", cascade=True)
    assert plan.datasets == ("employees", "organizations")
