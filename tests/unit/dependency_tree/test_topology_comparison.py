"""Юнит-тесты shared topology comparison core и match-service адаптера."""

from __future__ import annotations

import pytest

from connector.domain.dependency_tree import (
    TargetHierarchyTopologyBuilder,
    TopologyMatchMode,
    compare_topology_candidates,
)
from connector.domain.diagnostics import build_core_catalog
from connector.domain.ports.topology import TargetHierarchyRow
from connector.domain.transform_dsl import load_topology_spec_for_dataset
from connector.domain.transform_dsl.compilers.match import TopologyMatchPolicy
from connector.domain.transform_dsl.compilers.topology import TopologyDsl
from connector.usecases.topology_match import (
    build_source_locator_builder,
    build_topology_match_service,
)
from connector.domain.transform.core.source_record import SourceRecord

pytestmark = pytest.mark.unit


def _snapshot():
    snapshot, errors, warnings = TargetHierarchyTopologyBuilder(
        catalog=build_core_catalog(strict=True)
    ).build(
        (
            TargetHierarchyRow(node_id="10", parent_id=None, label="head office"),
            TargetHierarchyRow(node_id="20", parent_id="10", label="branch a"),
            TargetHierarchyRow(node_id="30", parent_id="10", label="branch b"),
            TargetHierarchyRow(node_id="100", parent_id="20", label="shared team"),
            TargetHierarchyRow(node_id="200", parent_id="30", label="shared team"),
            TargetHierarchyRow(node_id="300", parent_id="20", label="platform team"),
        )
    )
    assert errors == ()
    assert warnings == ()
    return snapshot


def _ladder(*modes: TopologyMatchMode) -> tuple[TopologyMatchMode, ...]:
    return tuple(modes)


def test_compare_returns_exact_canonical_path_match() -> None:
    result = compare_topology_candidates(
        snapshot=_snapshot(),
        source_segments=("head office", "branch a", "shared team"),
        candidate_ids=("100", "200"),
        ladder=_ladder(TopologyMatchMode.EXACT_CANONICAL_PATH),
    )

    assert result.mode == TopologyMatchMode.EXACT_CANONICAL_PATH
    assert result.matched_candidate_id == "100"
    assert result.reason == "resolved_by_exact_canonical_path"


def test_compare_returns_leaf_parent_chain_match() -> None:
    result = compare_topology_candidates(
        snapshot=_snapshot(),
        source_segments=("other root", "branch a", "shared team"),
        candidate_ids=("100", "200"),
        ladder=_ladder(TopologyMatchMode.EXACT_LEAF_PARENT_CHAIN),
    )

    assert result.mode == TopologyMatchMode.EXACT_LEAF_PARENT_CHAIN
    assert result.matched_candidate_id == "100"


def test_compare_returns_leaf_root_depth_match() -> None:
    result = compare_topology_candidates(
        snapshot=_snapshot(),
        source_segments=("head office", "unknown branch", "shared team"),
        candidate_ids=("100", "200"),
        ladder=_ladder(TopologyMatchMode.EXACT_LEAF_ROOT_DEPTH),
    )

    assert result.mode == TopologyMatchMode.AMBIGUOUS
    assert result.is_ambiguous is True
    assert result.reason == "ambiguous_on_exact_leaf_root_depth"


def test_compare_returns_no_match_when_ladder_cannot_confirm() -> None:
    result = compare_topology_candidates(
        snapshot=_snapshot(),
        source_segments=("head office", "branch c", "shared team"),
        candidate_ids=("100", "200"),
        ladder=_ladder(TopologyMatchMode.EXACT_CANONICAL_PATH),
    )

    assert result.mode == TopologyMatchMode.NO_MATCH
    assert result.matched_candidate_ids == ()
    assert result.reason == "no_topology_confirmation"


def test_topology_match_service_and_locator_builder_use_enum_policy(
    employees_registry_path,
) -> None:
    topology_spec = load_topology_spec_for_dataset("organizations")
    compiled_topology = TopologyDsl().compile(topology_spec)
    locator_builder = build_source_locator_builder(
        path_fields=(
            item.field for item in topology_spec.topology.source.path_columns
        ),
        canonicalizer=compiled_topology.python,
    )
    match_service = build_topology_match_service(
        snapshot=_snapshot(),
        policy=TopologyMatchPolicy(
            enabled=True,
            apply_on="ambiguous_only",
            on_missing_topology="skip",
            comparison_ladder=(
                TopologyMatchMode.EXACT_CANONICAL_PATH,
                TopologyMatchMode.EXACT_LEAF_PARENT_CHAIN,
            ),
        ),
    )

    assert locator_builder is not None
    assert match_service is not None

    locator = locator_builder.build(
        SourceRecord(
            line_no=1,
            record_id="line:1",
            values={
                "level_1_name": " Head Office ",
                "level_2_name": "Branch A",
                "level_3_name": "Shared Team",
            },
        )
    )

    assert locator is not None
    result = match_service.compare(locator, ("100", "200"))
    assert result.mode == TopologyMatchMode.EXACT_CANONICAL_PATH
    assert result.matched_target_id == "100"
