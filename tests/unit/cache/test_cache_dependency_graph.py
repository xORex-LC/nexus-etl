from __future__ import annotations

import pytest

from connector.domain.cache_core import CacheDependencyGraph


def test_refresh_order_uses_topological_order() -> None:
    graph = CacheDependencyGraph(
        datasets=("organizations", "employees", "positions"),
        dependencies={"employees": ("organizations",), "positions": ("organizations",)},
    )
    assert graph.refresh_order() == ["organizations", "employees", "positions"]


def test_refresh_order_for_single_dataset_keeps_current_runtime_behavior() -> None:
    graph = CacheDependencyGraph(
        datasets=("organizations", "employees"),
        dependencies={"employees": ("organizations",)},
    )
    assert graph.refresh_order(dataset="employees", include_dependencies=False) == ["employees"]


def test_clear_order_with_cascade_clears_dependents_first() -> None:
    graph = CacheDependencyGraph(
        datasets=("organizations", "employees"),
        dependencies={"employees": ("organizations",)},
    )
    assert graph.clear_order(dataset="organizations", cascade=True) == ["employees", "organizations"]


def test_unknown_dependency_is_rejected() -> None:
    with pytest.raises(ValueError, match="unknown dependencies"):
        CacheDependencyGraph(
            datasets=("employees",),
            dependencies={"employees": ("organizations",)},
        )


def test_cycle_is_rejected() -> None:
    with pytest.raises(ValueError, match="cycle"):
        CacheDependencyGraph(
            datasets=("a", "b"),
            dependencies={"a": ("b",), "b": ("a",)},
        )
