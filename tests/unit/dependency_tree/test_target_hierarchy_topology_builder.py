"""Юнит-тесты target-side topology builder-а и сборки forest-структуры."""

from __future__ import annotations

import pytest

from connector.domain.dependency_tree import TargetHierarchyTopologyBuilder
from connector.domain.diagnostics import build_core_catalog
from connector.domain.models import DiagnosticStage
from connector.domain.ports.topology import TargetHierarchyRow

pytestmark = pytest.mark.unit


def _builder() -> TargetHierarchyTopologyBuilder:
    return TargetHierarchyTopologyBuilder(catalog=build_core_catalog(strict=True))


def test_valid_adjacency_builds_snapshot_indices() -> None:
    snapshot, errors, warnings = _builder().build(
        (
            TargetHierarchyRow(node_id="root", parent_id=None, label="Root"),
            TargetHierarchyRow(node_id="child", parent_id="root", label="Child"),
            TargetHierarchyRow(node_id="leaf", parent_id="child", label="Leaf"),
        )
    )

    assert errors == ()
    assert warnings == ()
    assert snapshot.roots == ("root",)
    assert snapshot.parent_id("child") == "root"
    assert snapshot.children_ids("root") == ("child",)
    assert snapshot.children_ids("child") == ("leaf",)


def test_self_loop_returns_cycle_diagnostic_and_empty_snapshot() -> None:
    snapshot, errors, _ = _builder().build(
        (TargetHierarchyRow(node_id="self", parent_id="self", label="Self"),)
    )

    assert snapshot.nodes_by_id == {}
    assert len(errors) == 1
    assert errors[0].stage == DiagnosticStage.TOPOLOGY_BOOTSTRAP
    assert errors[0].code == "TOPOLOGY_CYCLE_DETECTED"


def test_cycle_returns_cycle_diagnostic() -> None:
    snapshot, errors, _ = _builder().build(
        (
            TargetHierarchyRow(node_id="a", parent_id="b", label="A"),
            TargetHierarchyRow(node_id="b", parent_id="a", label="B"),
        )
    )

    assert snapshot.nodes_by_id == {}
    assert [item.code for item in errors] == ["TOPOLOGY_CYCLE_DETECTED"]


def test_parent_missing_returns_diagnostic() -> None:
    snapshot, errors, _ = _builder().build(
        (
            TargetHierarchyRow(node_id="root", parent_id=None, label="Root"),
            TargetHierarchyRow(node_id="child", parent_id="missing", label="Child"),
        )
    )

    assert snapshot.nodes_by_id == {}
    assert [item.code for item in errors] == ["TOPOLOGY_PARENT_MISSING"]
    assert errors[0].details == {"node_id": "child", "parent_id": "missing"}


def test_duplicate_node_id_returns_diagnostic() -> None:
    snapshot, errors, _ = _builder().build(
        (
            TargetHierarchyRow(node_id="dup", parent_id=None, label="One"),
            TargetHierarchyRow(node_id="dup", parent_id=None, label="Two"),
        )
    )

    assert snapshot.nodes_by_id == {}
    assert [item.code for item in errors] == ["TOPOLOGY_DUPLICATE_NODE"]


def test_forest_keeps_all_roots() -> None:
    snapshot, errors, warnings = _builder().build(
        (
            TargetHierarchyRow(node_id="r1", parent_id=None, label="R1"),
            TargetHierarchyRow(node_id="r2", parent_id=None, label="R2"),
        )
    )

    assert errors == ()
    assert warnings == ()
    assert set(snapshot.roots) == {"r1", "r2"}
