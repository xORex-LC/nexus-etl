"""Юнит-тесты target topology readiness evaluator-а."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from connector.domain.dependency_tree import (
    TopologyNode,
    TopologySnapshot,
    TopologyTargetReadinessEvaluator,
)
from connector.domain.diagnostics import build_core_catalog
from connector.domain.models import DiagnosticSeverity, DiagnosticStage
from connector.domain.ports.topology import (
    TargetHierarchyReadMeta,
    TopologyFreshnessPolicy,
)

pytestmark = pytest.mark.unit


def _snapshot() -> TopologySnapshot:
    return TopologySnapshot(
        nodes_by_id={
            "root": TopologyNode(
                node_id="root",
                parent_id=None,
                display_name="Root",
                canonical_name="root",
            )
        },
        parent_by_id={"root": None},
        children_by_id={"root": ()},
        roots=("root",),
    )


def _evaluator(now: datetime) -> TopologyTargetReadinessEvaluator:
    return TopologyTargetReadinessEvaluator(
        catalog=build_core_catalog(strict=True),
        now_provider=lambda: now,
    )


def test_target_readiness_empty_snapshot_returns_topology_target_empty() -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    result = _evaluator(now).evaluate(
        snapshot=TopologySnapshot.empty(),
        metadata=TargetHierarchyReadMeta(
            cache_snapshot_revision="rev-1",
            refreshed_at=now,
            row_count=0,
        ),
        policy=TopologyFreshnessPolicy(mode="none"),
        require_target_topology=True,
    )

    assert result.is_ready is False
    assert [item.code for item in result.errors] == ["TOPOLOGY_TARGET_EMPTY"]
    assert result.warnings == ()
    assert result.errors[0].stage == DiagnosticStage.TOPOLOGY_BOOTSTRAP
    assert result.errors[0].severity == DiagnosticSeverity.ERROR
    assert result.details["reason"] == "snapshot_empty"


def test_target_readiness_stale_snapshot_returns_error_when_required() -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)
    refreshed_at = now - timedelta(minutes=10)

    result = _evaluator(now).evaluate(
        snapshot=_snapshot(),
        metadata=TargetHierarchyReadMeta(
            cache_snapshot_revision="rev-1",
            refreshed_at=refreshed_at,
            row_count=1,
        ),
        policy=TopologyFreshnessPolicy(mode="max_age", max_age_seconds=60),
        require_target_topology=True,
    )

    assert result.is_ready is False
    assert [item.code for item in result.errors] == ["TOPOLOGY_TARGET_STALE"]
    assert result.warnings == ()
    assert result.details["reason"] == "max_age_exceeded"
    assert result.details["max_age_seconds"] == 60
    assert result.details["age_seconds"] == 600


def test_target_readiness_missing_freshness_metadata_warns_when_optional() -> None:
    now = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)

    result = _evaluator(now).evaluate(
        snapshot=_snapshot(),
        metadata=TargetHierarchyReadMeta(
            cache_snapshot_revision=None,
            refreshed_at=None,
            row_count=1,
        ),
        policy=TopologyFreshnessPolicy(
            mode="max_age",
            max_age_seconds=60,
            require_revision=True,
        ),
        require_target_topology=False,
    )

    assert result.is_ready is False
    assert result.errors == ()
    assert [item.code for item in result.warnings] == ["TOPOLOGY_TARGET_STALE"]
    assert result.warnings[0].stage == DiagnosticStage.TOPOLOGY_BOOTSTRAP
    assert result.warnings[0].severity == DiagnosticSeverity.WARNING
    assert result.details["decision"] == "optional_skip"
    assert result.details["reason"] == "missing_cache_snapshot_revision"
