"""Юнит-тесты source-side topology builder-а и детерминированных id."""

from __future__ import annotations

import builtins
import pytest

from connector.domain.dependency_tree import SourcePathTopologyBuilder
from connector.domain.dependency_tree.fingerprints import build_source_synthetic_id
from connector.domain.diagnostics import build_core_catalog
from connector.domain.ports.topology import SourceTopologyCanonicalPath

pytestmark = pytest.mark.unit

EXPECTED_SOURCE_SYNTHETIC_ID = (
    "5008a653dd4d5f74a94a95073b37dbbe656ab5ddf2310a407729a230c76d67a1"
)


def _builder(*, normalization_version: str = "v1") -> SourcePathTopologyBuilder:
    return SourcePathTopologyBuilder(
        catalog=build_core_catalog(strict=True),
        normalization_version=normalization_version,
    )


def test_distinct_canonical_batch_builds_prefix_parent_chain() -> None:
    snapshot, errors, warnings = _builder().build(
        (
            SourceTopologyCanonicalPath(("root", "child", "leaf")),
            SourceTopologyCanonicalPath(("root", "child", "other")),
        )
    )

    assert errors == ()
    assert warnings == ()
    assert len(snapshot.nodes_by_id) == 4
    root_id = build_source_synthetic_id(("root",), normalization_version="v1")
    child_id = build_source_synthetic_id(("root", "child"), normalization_version="v1")
    leaf_id = build_source_synthetic_id(
        ("root", "child", "leaf"), normalization_version="v1"
    )
    assert snapshot.roots == (root_id,)
    assert snapshot.parent_id(child_id) == root_id
    assert snapshot.parent_id(leaf_id) == child_id


def test_source_builder_is_acyclic_by_construction() -> None:
    snapshot, errors, warnings = _builder().build(
        (
            SourceTopologyCanonicalPath(("a",)),
            SourceTopologyCanonicalPath(("a", "b")),
            SourceTopologyCanonicalPath(("a", "b", "c")),
        )
    )

    assert errors == ()
    assert warnings == ()
    for node_id in snapshot.nodes_by_id:
        assert node_id not in snapshot.ancestors(node_id)


def test_blank_path_to_builder_returns_error() -> None:
    snapshot, errors, warnings = _builder().build((SourceTopologyCanonicalPath(()),))

    assert snapshot.nodes_by_id == {}
    assert warnings == ()
    assert [item.code for item in errors] == ["TOPOLOGY_SOURCE_PATH_EMPTY"]


def test_gap_in_levels_is_reported_as_malformed_warning() -> None:
    snapshot, errors, warnings = _builder().build(
        (SourceTopologyCanonicalPath(("l1", "", "l3")),)
    )

    assert snapshot.nodes_by_id == {}
    assert errors == ()
    assert [item.code for item in warnings] == ["TOPOLOGY_SOURCE_PATH_MALFORMED"]


def test_one_path_produces_stable_known_id() -> None:
    synthetic_id = build_source_synthetic_id(
        ("root", "child"),
        normalization_version="v1",
    )

    assert synthetic_id == EXPECTED_SOURCE_SYNTHETIC_ID


def test_normalization_version_changes_source_ids() -> None:
    v1_snapshot, _, _ = _builder(normalization_version="v1").build(
        (SourceTopologyCanonicalPath(("root", "child")),)
    )
    v2_snapshot, _, _ = _builder(normalization_version="v2").build(
        (SourceTopologyCanonicalPath(("root", "child")),)
    )

    assert set(v1_snapshot.nodes_by_id) != set(v2_snapshot.nodes_by_id)


def test_source_ids_do_not_depend_on_python_hash() -> None:
    original_hash = builtins.hash
    builtins.hash = lambda _: 1  # type: ignore[assignment]
    try:
        synthetic_id = build_source_synthetic_id(
            ("root", "child"),
            normalization_version="v1",
        )
    finally:
        builtins.hash = original_hash

    assert synthetic_id == EXPECTED_SOURCE_SYNTHETIC_ID


def test_duplicate_canonical_path_is_kept_deterministically_with_warning() -> None:
    snapshot, errors, warnings = _builder().build(
        (
            SourceTopologyCanonicalPath(("root", "child")),
            SourceTopologyCanonicalPath(("root", "child")),
        )
    )

    assert errors == ()
    assert len(snapshot.nodes_by_id) == 2
    assert [item.code for item in warnings] == ["TOPOLOGY_SOURCE_COLLISION"]
    assert warnings[0].details == {
        "canonical_segments": ("root", "child"),
        "kept_path_index": 0,
        "dropped_path_index": 1,
    }
