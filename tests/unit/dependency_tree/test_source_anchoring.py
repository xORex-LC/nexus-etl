"""Юнит-тесты source-side anchoring core Stage G."""

from __future__ import annotations

import pytest

from connector.domain.dependency_tree import SourceAdjacencyNode, anchor_source_nodes

pytestmark = pytest.mark.unit


def test_anchor_source_nodes_keeps_forward_reference_when_parent_is_in_batch() -> None:
    result = anchor_source_nodes(
        (
            SourceAdjacencyNode(node_id="child", parent_id="parent", label="Child"),
            SourceAdjacencyNode(node_id="parent", parent_id=None, label="Parent"),
        ),
        target_ids=frozenset(),
    )

    assert result.anchored_ids == frozenset({"parent", "child"})
    assert result.dropped == {}


def test_anchor_source_nodes_drops_missing_parent_subtree() -> None:
    result = anchor_source_nodes(
        (
            SourceAdjacencyNode(node_id="382", parent_id="378", label="Service"),
            SourceAdjacencyNode(node_id="383", parent_id="382", label="Subservice"),
        ),
        target_ids=frozenset({"100"}),
    )

    assert result.anchored_ids == frozenset()
    assert result.dropped["382"].reason == "missing_parent"
    assert result.dropped["382"].broken_at_parent_id == "378"
    assert result.dropped["383"].reason == "unanchored_subtree"
    assert result.dropped["383"].broken_at_parent_id == "378"


def test_anchor_source_nodes_anchors_against_target_membership() -> None:
    result = anchor_source_nodes(
        (
            SourceAdjacencyNode(node_id="382", parent_id="target-root", label="Service"),
        ),
        target_ids=frozenset({"target-root"}),
    )

    assert result.anchored_ids == frozenset({"382"})
    assert result.dropped == {}


def test_anchor_source_nodes_marks_cycle_as_dropped() -> None:
    result = anchor_source_nodes(
        (
            SourceAdjacencyNode(node_id="a", parent_id="b", label="A"),
            SourceAdjacencyNode(node_id="b", parent_id="a", label="B"),
        ),
        target_ids=frozenset(),
    )

    assert set(result.dropped) == {"a", "b"}
    assert {verdict.reason for verdict in result.dropped.values()} == {"cycle"}
