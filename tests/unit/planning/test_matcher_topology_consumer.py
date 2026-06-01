"""Юнит-тесты topology-aware consumer-а в MatchCore."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest

from connector.domain.dependency_tree import TargetHierarchyTopologyBuilder, TopologyMatchMode
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.ports.topology import TargetHierarchyRow
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.ids.match_key import MatchKey
from connector.domain.transform.matcher.context import MatchContext
from connector.domain.transform.matcher.dedup_store import LocalSourceDedupStore
from connector.domain.transform.matcher.match_core import MatchCore
from connector.domain.transform.matcher.match_models import (
    MatchDecisionReason,
    MatchDecisionStatus,
)
from connector.domain.transform.matcher.ports import ISourceDedupStore
from connector.domain.transform_dsl import load_match_spec_for_dataset, load_topology_spec_for_dataset
from connector.domain.transform_dsl.compilers.match import MatchDsl
from connector.domain.transform_dsl.compilers.resolve import ResolveRules
from connector.domain.transform_dsl.compilers.topology import TopologyDsl
from connector.usecases.topology_match import (
    build_source_locator_builder,
    build_topology_match_service,
)
from connector.domain.models import RowRef

pytestmark = pytest.mark.unit


@dataclass
class _FakeCacheRepo:
    responses: dict[tuple[str, str], list[dict]]

    def find(
        self,
        dataset: str,
        filters: dict[str, str],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> list[dict]:
        _ = (dataset, include_deleted, mode)
        key, value = next(iter(filters.items()))
        return list(self.responses.get((key, value), []))

    def set_runtime_state(self, scope: str, dataset: str, state_key: str, state_value: str) -> None:
        _ = (scope, dataset, state_key, state_value)

    def get_runtime_state(self, scope: str, dataset: str, state_key: str) -> str | None:
        _ = (scope, dataset, state_key)
        return None

    def clear_runtime_scope(self, scope: str) -> None:
        _ = scope


def _snapshot():
    snapshot, errors, warnings = TargetHierarchyTopologyBuilder(
        catalog=build_catalog("organizations", strict=True)
    ).build(
        (
            TargetHierarchyRow(node_id="10", parent_id=None, label="head office"),
            TargetHierarchyRow(node_id="20", parent_id="10", label="branch a"),
            TargetHierarchyRow(node_id="30", parent_id="10", label="branch b"),
            TargetHierarchyRow(node_id="100", parent_id="20", label="shared team"),
            TargetHierarchyRow(node_id="200", parent_id="30", label="shared team"),
        )
    )
    assert errors == ()
    assert warnings == ()
    return snapshot


def _resolve_rules() -> ResolveRules:
    return ResolveRules(
        build_desired_state=lambda row, _ctx: {
            "code": row["code"],
            "name": row["name"],
            "parent_id": row["parent_id"],
        }
    )


def _match_result(*, raw_values: dict[str, object]) -> TransformResult:
    match_context = MatchContext(
        line_no=1,
        match_key="SRC-001",
        match_key_complete=True,
        row_ref=RowRef(
            line_no=1,
            row_id="line:1",
            identity_primary="match_key",
            identity_value="SRC-001",
        ),
    )
    row = {
        "code": "SRC-001",
        "name": "Shared Team",
        "parent_id": 20,
        "target_id": None,
    }
    return TransformResult(
        record=SourceRecord(line_no=1, record_id="line:1", values=raw_values),
        row=row,
        row_ref=match_context.row_ref,
        match_key=MatchKey(match_context.match_key),
        errors=(),
        warnings=(),
    )


def _core(cache_repo: _FakeCacheRepo) -> MatchCore:
    match_rules = MatchDsl().compile(load_match_spec_for_dataset("organizations"))
    topology_spec = load_topology_spec_for_dataset("organizations")
    compiled_topology = TopologyDsl().compile(topology_spec)
    return MatchCore(
        dataset="organizations",
        cache_gateway=cache_repo,
        matching_rules=match_rules,
        resolve_rules=_resolve_rules(),
        include_deleted=False,
        catalog=build_catalog("organizations", strict=True),
        dedup_store=cast(ISourceDedupStore, LocalSourceDedupStore()),
        topology_match_service=build_topology_match_service(
            snapshot=_snapshot(),
            policy=match_rules.topology,
        ),
        source_topology_locator_builder=build_source_locator_builder(
            path_fields=(
                item.field for item in topology_spec.topology.source.path_columns
            ),
            canonicalizer=compiled_topology.python,
        ),
        topology_target_node_id_field=topology_spec.topology.target.node_id_field,
    )


def test_match_core_refines_ambiguous_fuzzy_candidates_with_topology(
    employees_registry_path,
) -> None:
    cache_repo = _FakeCacheRepo(
        responses={
            ("match_key", "SRC-001"): [],
            ("name", "Shared Team"): [
                {"_id": "org-a", "_ouid": "100", "name": "Shared Team", "code": "A-100"},
                {"_id": "org-b", "_ouid": "200", "name": "Shared Team", "code": "B-200"},
            ],
        }
    )

    result = _core(cache_repo).match(
        _match_result(
            raw_values={
                "level_1_name": "Head Office",
                "level_2_name": "Branch A",
                "level_3_name": "Shared Team",
            }
        )
    )

    assert result.row is not None
    decision = result.row.match_decision
    assert decision.status == MatchDecisionStatus.MATCHED
    assert decision.reason_code == MatchDecisionReason.TOPOLOGY_EXACT_CANONICAL_PATH
    assert decision.topology_match_mode == TopologyMatchMode.EXACT_CANONICAL_PATH
    assert decision.topology_reason == "resolved_by_exact_canonical_path"
    assert decision.selected is not None
    assert decision.selected.target_id == "org-a"
    assert decision.selected.match_mode == "exact_canonical_path"


def test_match_core_returns_hard_error_when_topology_locator_is_missing(
    employees_registry_path,
) -> None:
    cache_repo = _FakeCacheRepo(
        responses={
            ("match_key", "SRC-001"): [],
            ("name", "Shared Team"): [
                {"_id": "org-a", "_ouid": "100", "name": "Shared Team", "code": "A-100"},
                {"_id": "org-b", "_ouid": "200", "name": "Shared Team", "code": "B-200"},
            ],
        }
    )

    result = _core(cache_repo).match(
        _match_result(raw_values={})
    )

    assert result.row is None
    assert [item.code for item in result.errors] == ["TOPOLOGY_SOURCE_PATH_EMPTY"]


def test_match_core_aligns_selected_score_with_topology_resolved_candidate(
    employees_registry_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_repo = _FakeCacheRepo(
        responses={
            ("match_key", "SRC-001"): [],
        }
    )
    core = _core(cache_repo)

    def _fake_match_with_fuzzy(*, row, desired_state, identity):
        _ = (row, desired_state, identity)
        candidate_a = {"_id": "org-a", "_ouid": "100", "name": "Shared Team", "code": "A-100"}
        candidate_b = {"_id": "org-b", "_ouid": "200", "name": "Shared Team", "code": "B-200"}
        return (
            None,
            MatchDecisionStatus.AMBIGUOUS,
            0.82,
            MatchDecisionReason.FUZZY_REVIEW,
            (candidate_a, candidate_b),
            {
                "id:org-a": 0.82,
                "id:org-b": 0.74,
            },
            (
                {"target_id": "org-a", "score": 0.82},
                {"target_id": "org-b", "score": 0.74},
            ),
        )

    monkeypatch.setattr(core, "_match_with_fuzzy", _fake_match_with_fuzzy)

    result = core.match(
        _match_result(
            raw_values={
                "level_1_name": "Head Office",
                "level_2_name": "Branch B",
                "level_3_name": "Shared Team",
            }
        )
    )

    assert result.row is not None
    decision = result.row.match_decision
    assert decision.status == MatchDecisionStatus.MATCHED
    assert decision.reason_code == MatchDecisionReason.TOPOLOGY_EXACT_CANONICAL_PATH
    assert decision.selected is not None
    assert decision.selected.target_id == "org-b"
    assert decision.selected.score == 0.74
    assert decision.score == 0.74
