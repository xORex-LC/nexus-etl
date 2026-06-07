"""Юнит-тесты query-семантики неизменяемого topology snapshot-а."""

from __future__ import annotations

import pytest

from connector.domain.dependency_tree import TargetHierarchyTopologyBuilder
from connector.domain.diagnostics import build_core_catalog
from connector.domain.ports.topology import TargetHierarchyRow

pytestmark = pytest.mark.unit


def _snapshot():
    snapshot, errors, warnings = TargetHierarchyTopologyBuilder(
        catalog=build_core_catalog(strict=True)
    ).build(
        (
            TargetHierarchyRow(node_id="r1", parent_id=None, label="Root One"),
            TargetHierarchyRow(node_id="a", parent_id="r1", label="A"),
            TargetHierarchyRow(node_id="b", parent_id="a", label="B"),
            TargetHierarchyRow(node_id="c", parent_id="a", label="C"),
            TargetHierarchyRow(node_id="r2", parent_id=None, label="Root Two"),
            TargetHierarchyRow(node_id="d", parent_id="r2", label="D"),
        )
    )
    assert errors == ()
    assert warnings == ()
    return snapshot


def test_snapshot_indices_are_read_only() -> None:
    snapshot = _snapshot()

    with pytest.raises(TypeError):
        snapshot.nodes_by_id["x"] = snapshot.require_node("a")  # type: ignore[index]
    with pytest.raises(TypeError):
        snapshot.parent_by_id["a"] = None  # type: ignore[index]


def test_path_to_root_and_ancestors_follow_deep_branch() -> None:
    snapshot = _snapshot()

    assert snapshot.path_to_root("b") == ("b", "a", "r1")
    assert snapshot.ancestors("b") == ("a", "r1")


def test_depth_and_root_id_work_in_forest() -> None:
    snapshot = _snapshot()

    assert snapshot.depth("r1") == 0
    assert snapshot.depth("b") == 2
    assert snapshot.root_id("b") == "r1"
    assert snapshot.root_id("d") == "r2"


def test_canonical_path_returns_root_to_leaf_segments() -> None:
    snapshot = _snapshot()

    assert snapshot.canonical_path("b") == ("Root One", "A", "B")


def test_descendants_return_complete_subtree() -> None:
    snapshot = _snapshot()

    assert set(snapshot.descendants("a")) == {"b", "c"}


def test_structural_signature_is_equal_for_same_node_and_differs_for_other_branch() -> (
    None
):
    snapshot = _snapshot()

    assert snapshot.structural_signature("b") == snapshot.structural_signature("b")
    assert snapshot.structural_signature("b") != snapshot.structural_signature("d")
