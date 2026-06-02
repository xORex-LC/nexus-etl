"""Юнит-тесты Stage D topology bootstrap orchestration и activation matrix."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from connector.domain.dependency_tree import TopologyNode, TopologySnapshot
from connector.domain.models import DiagnosticItem, DiagnosticSeverity, DiagnosticStage
from connector.domain.ports.topology import (
    TargetHierarchyReadMeta,
    TopologyTargetReadinessResult,
)
from connector.domain.transform_dsl import load_topology_spec_for_dataset
from connector.usecases.topology_bootstrap import (
    TopologyBootstrapRequest,
    TopologyBootstrapUseCase,
    TopologyRequirementResolver,
    TopologyRuntimeBinding,
    TraceToSink,
)
from connector.usecases.topology_target_build import TargetTopologyBuildResult

pytestmark = pytest.mark.unit


@dataclass
class _RecordingEventSink:
    events: list[tuple[int, str, dict]] | None = None
    debug_enabled: bool = True

    def __post_init__(self) -> None:
        if self.events is None:
            self.events = []

    def enabled(self, level: int) -> bool:
        return self.debug_enabled or level > logging.DEBUG

    def emit(self, *, level: int, event: str, payload) -> None:
        self.events.append((level, event, dict(payload)))


def _ready_snapshot() -> TopologySnapshot:
    return TopologySnapshot(
        nodes_by_id={
            "100": TopologyNode(
                node_id="100",
                parent_id=None,
                display_name="Head Office",
                canonical_name="head office",
            ),
        },
        parent_by_id={"100": None},
        children_by_id={"100": ()},
        roots=("100",),
    )


def _ready_result() -> TargetTopologyBuildResult:
    return TargetTopologyBuildResult(
        snapshot=_ready_snapshot(),
        metadata=TargetHierarchyReadMeta(
            cache_snapshot_revision="rev-42",
            refreshed_at=None,
            row_count=1,
        ),
        readiness=TopologyTargetReadinessResult(
            is_ready=True,
            errors=(),
            warnings=(),
            details={
                "decision": "ready",
                "reason": "ready",
                "freshness_present": True,
            },
        ),
    )


def _error_result() -> TargetTopologyBuildResult:
    return TargetTopologyBuildResult(
        snapshot=TopologySnapshot.empty(),
        metadata=TargetHierarchyReadMeta(
            cache_snapshot_revision=None,
            refreshed_at=None,
            row_count=0,
        ),
        readiness=TopologyTargetReadinessResult(
            is_ready=False,
            errors=(
                DiagnosticItem(
                    stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
                    code="TOPOLOGY_TARGET_EMPTY",
                    field=None,
                    message="empty",
                    severity=DiagnosticSeverity.ERROR,
                ),
            ),
            warnings=(),
            details={
                "decision": "required_failure",
                "reason": "snapshot_empty",
                "freshness_present": False,
            },
        ),
    )


def test_topology_requirement_resolver_skips_mapping_pipeline_stage(
    employees_registry_path,
) -> None:
    resolver = TopologyRequirementResolver()

    decision = resolver.resolve(
        command_name="mapping",
        dataset_name="organizations",
    )

    assert decision.capability_enabled is True
    assert decision.request.require_source_topology is False
    assert decision.request.require_target_topology is False
    assert decision.activation_sources == ()


def test_topology_requirement_resolver_activates_match_policy(
    employees_registry_path,
) -> None:
    resolver = TopologyRequirementResolver()

    decision = resolver.resolve(
        command_name="match",
        dataset_name="organizations",
    )

    assert decision.activated is True
    # Phase 1a/1b работают от row-level canonical path: source snapshot не требуется (Stage G+).
    assert decision.request.require_source_topology is False
    assert decision.request.require_target_topology is True
    assert decision.activation_sources == ("match",)
    assert decision.target_failure_is_hard is True


def test_topology_requirement_resolver_activates_link_policy_for_target_dataset(
    employees_registry_path,
) -> None:
    resolver = TopologyRequirementResolver()

    decision = resolver.resolve(
        command_name="resolve",
        dataset_name="employees",
    )

    assert decision.activated is True
    # Phase 1a/1b работают от row-level canonical path: source snapshot не требуется (Stage G+).
    assert decision.request.require_source_topology is False
    assert decision.request.require_target_topology is True
    assert decision.request.topology_dataset == "organizations"
    assert decision.activation_sources == ("resolve",)
    assert decision.target_failure_is_hard is True


def test_topology_requirement_resolver_flags_capability_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Policy включена, но topology capability выключена → activation_error (не graceful skip)."""
    resolver = TopologyRequirementResolver()
    monkeypatch.setattr(
        resolver,
        "_load_capability",
        staticmethod(lambda _dataset: SimpleNamespace(enabled=False, spec=None)),
    )
    monkeypatch.setattr(
        resolver,
        "_load_match_policy",
        staticmethod(
            lambda _dataset: SimpleNamespace(enabled=True, on_missing_topology="skip")
        ),
    )

    decision = resolver.resolve(command_name="match", dataset_name="employees")

    assert decision.activated is False
    assert decision.activation_error is not None
    assert "capability is disabled" in decision.activation_error


def test_topology_requirement_resolver_returns_false_when_capability_disabled(
    employees_registry_path,
) -> None:
    resolver = TopologyRequirementResolver()

    decision = resolver.resolve(
        command_name="match",
        dataset_name="employees",
    )

    assert decision.capability_enabled is False
    assert decision.activated is False
    assert decision.request.require_source_topology is False
    assert decision.request.require_target_topology is False


def test_topology_bootstrap_usecase_returns_artifacts_and_normalizes_dataset(
    employees_registry_path,
) -> None:
    sink = _RecordingEventSink()
    observed: dict[str, str] = {}

    class _FakeTargetUseCase:
        def build(self, *, dataset, freshness_policy, require_target_topology):
            observed["dataset"] = dataset
            observed["policy_mode"] = freshness_policy.mode
            observed["require_target_topology"] = str(require_target_topology)
            return _ready_result()

    usecase = TopologyBootstrapUseCase(
        target_usecase_factory=lambda _spec, _compiled: _FakeTargetUseCase(),
        event_sink=sink,
        topology_loader=lambda dataset: load_topology_spec_for_dataset(dataset),
    )

    result = usecase.run(
        request=TopologyBootstrapRequest(
            pipeline_dataset="organizations",
            topology_dataset=None,
            run_id="run-1",
            require_source_topology=True,
            require_target_topology=True,
        ),
        target_failure_is_hard=True,
    )

    assert result.errors == ()
    assert result.warnings == ()
    assert result.artifacts is not None
    assert result.artifacts.metadata.dataset_name == "organizations"
    assert result.artifacts.target_snapshot is not None
    assert result.artifacts.metadata.topology_normalization_version.startswith("sha256:")
    assert observed == {
        "dataset": "organizations",
        "policy_mode": "none",
        "require_target_topology": "True",
    }
    assert [event for _, event, _ in sink.events] == [
        "bootstrap.start",
        "spec.loaded",
        "canonicalizer.compiled",
        "readiness.evaluated",
        "target.build.finish",
        "bootstrap.finish",
    ]


def test_topology_bootstrap_usecase_returns_no_artifacts_on_fatal_diagnostics(
    employees_registry_path,
) -> None:
    sink = _RecordingEventSink()

    class _FakeTargetUseCase:
        def build(self, *, dataset, freshness_policy, require_target_topology):
            return _error_result()

    usecase = TopologyBootstrapUseCase(
        target_usecase_factory=lambda _spec, _compiled: _FakeTargetUseCase(),
        event_sink=sink,
        topology_loader=lambda dataset: load_topology_spec_for_dataset(dataset),
    )

    result = usecase.run(
        request=TopologyBootstrapRequest(
            pipeline_dataset="organizations",
            topology_dataset=None,
            run_id="run-1",
            require_source_topology=True,
            require_target_topology=True,
        ),
        target_failure_is_hard=True,
    )

    assert result.artifacts is None
    assert [item.code for item in result.errors] == ["TOPOLOGY_TARGET_EMPTY"]
    assert result.warnings == ()


def test_topology_runtime_binding_exports_runtime_requirements() -> None:
    binding = TopologyRuntimeBinding(
        provider=None,
        request=TopologyBootstrapRequest(
            pipeline_dataset="employees",
            topology_dataset=None,
            run_id="run-1",
            require_source_topology=False,
            require_target_topology=True,
        ),
        artifacts=None,
        errors=(),
        warnings=(),
        activation_sources=("match",),
        skipped_reason="capability_disabled",
    )

    requirements = binding.to_runtime_requirements()

    assert requirements.pipeline_dataset == "employees"
    assert requirements.topology_dataset == "employees"
    assert requirements.requires_target_topology is True
    assert requirements.activation_sources == ("match",)
    assert requirements.skipped_reason == "capability_disabled"


def test_trace_to_sink_emits_expected_debug_payloads() -> None:
    sink = _RecordingEventSink(debug_enabled=True)
    trace = TraceToSink.from_sink(sink=sink, namespace="target")

    trace.node_ingested(node_id="200", parent_id="100", canonical_name="finance")
    trace.cycle_checked(nodes=2, has_cycle=False)

    assert [event for _, event, _ in sink.events] == [
        "target.node_ingested",
        "target.cycle_check",
    ]
    assert sink.events[0][2]["canonical_name"] == "finance"
    assert sink.events[1][2]["has_cycle"] is False


def test_trace_to_sink_returns_null_trace_when_debug_disabled() -> None:
    sink = _RecordingEventSink(debug_enabled=False)
    trace = TraceToSink.from_sink(sink=sink, namespace="target")

    trace.node_ingested(node_id="200", parent_id="100", canonical_name="finance")

    assert sink.events == []
