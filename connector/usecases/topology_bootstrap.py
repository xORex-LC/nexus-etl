"""Topology bootstrap orchestration — requirement resolution и run-scoped artifacts.

Содержит orchestration-level контракты для pre-handler topology bootstrap:
activation resolver, run-scoped artifacts/provider и target-only bootstrap use case
текущей фазы. Domain builders/readiness остаются ниже; CLI/runtime wiring живёт
выше, в delivery runtime step.

Зона ответственности:
    - Нормализовать activation decision для match/resolve/import-plan
    - Оркестрировать topology spec load, canonicalizer compile и target build path
    - Собрать run-scoped artifacts и snapshot-only provider

Вне области ответственности:
    - CLI lifecycle, DI container init/shutdown и report finalization
    - Match/resolve consumer semantics Phase 1a/1b
    - Source projection / Polars bootstrap
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from connector.domain.dependency_tree import NullTopologyTrace, TopologySnapshot, TopologyTracePort
from connector.domain.ports.topology import (
    TopologyEventSink,
    TopologyNotAvailableError,
    TopologyProviderPort,
    TopologyRuntimeRequirements,
)
from connector.domain.models import DiagnosticItem
from connector.domain.transform_dsl import (
    load_match_spec_for_dataset,
    load_resolve_spec_for_dataset,
    load_sink_spec_for_dataset,
    load_topology_spec_for_dataset,
)
from connector.domain.transform_dsl.compilers.topology import TopologyDsl
from connector.usecases.topology_target_build import (
    TargetTopologyBuildResult,
    TargetTopologyBuildUseCase,
)


@dataclass(frozen=True)
class TopologyBuildMetadata:
    """Provenance-факты topology bootstrap-а для report и future consumers."""

    dataset_name: str
    source_file_fingerprint: str | None
    cache_snapshot_revision: str | None
    built_at: datetime
    topology_normalization_version: str


@dataclass(frozen=True)
class TopologyRunArtifacts:
    """Run-scoped topology artifacts текущего bootstrap-а."""

    source_snapshot: TopologySnapshot | None
    target_snapshot: TopologySnapshot | None
    metadata: TopologyBuildMetadata


@dataclass(frozen=True)
class TopologyBootstrapResult:
    """Итог bootstrap-а без knowledge о CLI/runtime short-circuit policy."""

    artifacts: TopologyRunArtifacts | None
    errors: tuple[DiagnosticItem, ...]
    warnings: tuple[DiagnosticItem, ...]


@dataclass(frozen=True)
class TopologyBootstrapRequest:
    """Routing/activation request для topology bootstrap boundary."""

    pipeline_dataset: str
    topology_dataset: str | None
    run_id: str
    require_source_topology: bool
    require_target_topology: bool


@dataclass(frozen=True)
class TopologyActivationDecision:
    """Решение activation resolver-а для конкретной команды и датасета."""

    request: TopologyBootstrapRequest
    capability_enabled: bool
    activation_sources: tuple[str, ...]
    target_failure_is_hard: bool
    skipped_reason: str | None = None
    # Конфликт конфигурации: consumer policy (match/resolve) включена, но topology
    # capability у целевого датасета выключена. Не graceful skip — bootstrap step
    # обязан short-circuit-ить команду с catalog-диагностикой TOPOLOGY_CAPABILITY_DISABLED.
    activation_error: str | None = None

    @property
    def activated(self) -> bool:
        return (
            self.capability_enabled
            and bool(self.activation_sources)
            and self.request.require_target_topology
        )


@dataclass(frozen=True)
class TopologyRuntimeBinding:
    """Run-scoped topology runtime binding для handler-scope pipeline wiring."""

    provider: TopologyProviderPort | None
    request: TopologyBootstrapRequest
    artifacts: TopologyRunArtifacts | None
    errors: tuple[DiagnosticItem, ...]
    warnings: tuple[DiagnosticItem, ...]
    activation_sources: tuple[str, ...]
    skipped_reason: str | None = None

    def to_runtime_requirements(self) -> TopologyRuntimeRequirements:
        """Build domain-level topology activation contract for pipeline composition."""

        return TopologyRuntimeRequirements(
            pipeline_dataset=self.request.pipeline_dataset,
            topology_dataset=self.request.topology_dataset or self.request.pipeline_dataset,
            requires_source_topology=self.request.require_source_topology,
            requires_target_topology=self.request.require_target_topology,
            activation_sources=self.activation_sources,
            skipped_reason=self.skipped_reason,
        )

    def report_context_payload(self) -> dict[str, Any]:
        """Собрать report payload для `ReportContextKey.TOPOLOGY`."""

        metadata = self.artifacts.metadata if self.artifacts is not None else None
        built_sides: list[str] = []
        if self.artifacts is not None and self.artifacts.source_snapshot is not None:
            built_sides.append("source")
        if self.artifacts is not None and self.artifacts.target_snapshot is not None:
            built_sides.append("target")
        if self.errors:
            status = "error"
        elif self.warnings:
            status = "warn"
        elif self.skipped_reason is not None:
            status = "skipped"
        else:
            status = "ok"
        return {
            "pipeline_dataset": self.request.pipeline_dataset,
            "topology_dataset": (
                self.request.topology_dataset or self.request.pipeline_dataset
            ),
            "requires_source_topology": self.request.require_source_topology,
            "requires_target_topology": self.request.require_target_topology,
            "activation_sources": list(self.activation_sources),
            "status": status,
            "built_sides": built_sides,
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "skip_reason": self.skipped_reason,
            "cache_snapshot_revision": (
                metadata.cache_snapshot_revision if metadata is not None else None
            ),
            "source_file_fingerprint": (
                metadata.source_file_fingerprint if metadata is not None else None
            ),
            "topology_normalization_version": (
                metadata.topology_normalization_version if metadata is not None else None
            ),
            "built_at": (
                metadata.built_at.isoformat() if metadata is not None else None
            ),
            "source_snapshot_nodes": (
                len(self.artifacts.source_snapshot.nodes_by_id)
                if self.artifacts is not None and self.artifacts.source_snapshot is not None
                else 0
            ),
            "target_snapshot_nodes": (
                len(self.artifacts.target_snapshot.nodes_by_id)
                if self.artifacts is not None and self.artifacts.target_snapshot is not None
                else 0
            ),
        }


class StaticTopologyProvider(TopologyProviderPort):
    """Snapshot-only provider для уже построенных topology artifacts."""

    def __init__(
        self,
        *,
        source_snapshot: TopologySnapshot | None,
        target_snapshot: TopologySnapshot | None,
    ) -> None:
        self._source_snapshot = source_snapshot
        self._target_snapshot = target_snapshot

    def require_source(self) -> TopologySnapshot:
        if self._source_snapshot is None:
            raise TopologyNotAvailableError(
                "Source topology snapshot is not available"
            )
        return self._source_snapshot

    def require_target(self) -> TopologySnapshot:
        if self._target_snapshot is None:
            raise TopologyNotAvailableError(
                "Target topology snapshot is not available"
            )
        return self._target_snapshot

    def get_source(self) -> TopologySnapshot | None:
        return self._source_snapshot

    def get_target(self) -> TopologySnapshot | None:
        return self._target_snapshot


class TraceToSink(TopologyTracePort):
    """Адаптер domain-trace -> `TopologyEventSink` для DEBUG веток."""

    def __init__(self, *, sink: TopologyEventSink, namespace: str) -> None:
        self._sink = sink
        self._namespace = namespace

    @classmethod
    def from_sink(
        cls,
        *,
        sink: TopologyEventSink,
        namespace: str,
    ) -> TopologyTracePort:
        if not sink.enabled(logging.DEBUG):
            return NullTopologyTrace()
        return cls(sink=sink, namespace=namespace)

    def node_ingested(
        self,
        *,
        node_id: str,
        parent_id: str | None,
        canonical_name: str,
    ) -> None:
        self._sink.emit(
            level=logging.DEBUG,
            event=f"{self._namespace}.node_ingested",
            payload={
                "node_id": node_id,
                "parent_id": parent_id,
                "canonical_name": canonical_name,
            },
        )

    def path_ingested(
        self,
        *,
        canonical_segments: tuple[str, ...],
        synthetic_node_id: str,
    ) -> None:
        self._sink.emit(
            level=logging.DEBUG,
            event=f"{self._namespace}.path_ingested",
            payload={
                "canonical_segments": list(canonical_segments),
                "synthetic_node_id": synthetic_node_id,
            },
        )

    def cycle_checked(self, *, nodes: int, has_cycle: bool) -> None:
        self._sink.emit(
            level=logging.DEBUG,
            event=f"{self._namespace}.cycle_check",
            payload={
                "algo": "graphlib",
                "nodes": nodes,
                "has_cycle": has_cycle,
            },
        )


# Единый источник истины о command-vocabulary для topology activation.
# Это имена команд (app.py), НЕ значения CheckpointName ("map" != "mapping").
# Команды, чей checkpoint включает Match или идёт после него — кандидаты на bootstrap.
TOPOLOGY_PIPELINE_COMMANDS: frozenset[str] = frozenset(
    {"mapping", "normalize", "enrich", "match", "resolve", "import-plan"}
)
# Pre-Match checkpoints: capability видна, но bootstrap не нужен.
_PRE_MATCH_COMMANDS: frozenset[str] = frozenset({"mapping", "normalize", "enrich"})
# Подмножество, активирующее topology-aware match.
_MATCH_ACTIVATING_COMMANDS: frozenset[str] = frozenset({"match", "import-plan"})
# Подмножество, активирующее topology-backed resolve link.
_RESOLVE_ACTIVATING_COMMANDS: frozenset[str] = frozenset({"resolve", "import-plan"})


class TopologyRequirementResolver:
    """Материализовать activation decision из command checkpoint и topology policy."""

    _PIPELINE_COMMANDS = TOPOLOGY_PIPELINE_COMMANDS

    def resolve(
        self,
        *,
        command_name: str,
        dataset_name: str,
    ) -> TopologyActivationDecision:
        normalized_command = command_name.strip().lower()
        if normalized_command not in self._PIPELINE_COMMANDS:
            return TopologyActivationDecision(
                request=TopologyBootstrapRequest(
                    pipeline_dataset=dataset_name,
                    topology_dataset=None,
                    run_id="",
                    require_source_topology=False,
                    require_target_topology=False,
                ),
                capability_enabled=False,
                activation_sources=(),
                target_failure_is_hard=False,
                skipped_reason="command_not_supported",
            )

        capability = self._load_capability(dataset_name)
        if normalized_command in _PRE_MATCH_COMMANDS:
            return TopologyActivationDecision(
                request=TopologyBootstrapRequest(
                    pipeline_dataset=dataset_name,
                    topology_dataset=None,
                    run_id="",
                    require_source_topology=False,
                    require_target_topology=False,
                ),
                capability_enabled=bool(capability and capability.enabled),
                activation_sources=(),
                target_failure_is_hard=False,
                skipped_reason=(
                    "checkpoint_before_topology_consumer"
                    if capability is not None and capability.enabled
                    else "capability_disabled"
                ),
            )

        match_policy = (
            self._load_match_policy(dataset_name)
            if normalized_command in _MATCH_ACTIVATING_COMMANDS
            else None
        )
        resolve_policy = (
            self._load_resolve_policy(dataset_name)
            if normalized_command in _RESOLVE_ACTIVATING_COMMANDS
            else None
        )
        topology_dataset = dataset_name

        activation_sources: list[str] = []
        target_failure_is_hard = False
        capability_enabled = False
        if (
            normalized_command in _MATCH_ACTIVATING_COMMANDS
            and match_policy is not None
            and match_policy.enabled
        ):
            capability = self._load_capability(dataset_name)
            if capability is not None and capability.enabled:
                capability_enabled = True
                topology_dataset = dataset_name
                activation_sources.append("match")
                if match_policy.on_missing_topology == "hard_error":
                    target_failure_is_hard = True
            else:
                return TopologyActivationDecision(
                    request=TopologyBootstrapRequest(
                        pipeline_dataset=dataset_name,
                        topology_dataset=None,
                        run_id="",
                        require_source_topology=False,
                        require_target_topology=False,
                    ),
                    capability_enabled=False,
                    activation_sources=(),
                    target_failure_is_hard=False,
                    skipped_reason="capability_disabled",
                    activation_error=(
                        f"match topology policy is enabled for dataset '{dataset_name}', "
                        "but its topology capability is disabled"
                    ),
                )
        if (
            normalized_command in _RESOLVE_ACTIVATING_COMMANDS
            and resolve_policy is not None
            and resolve_policy.enabled
        ):
            resolve_capability = self._load_resolve_topology_capability(
                dataset_name=dataset_name,
                field=resolve_policy.field,
            )
            if (
                resolve_capability is not None
                and resolve_capability.capability is not None
                and resolve_capability.capability.enabled
            ):
                capability_enabled = True
                if activation_sources and topology_dataset != resolve_capability.target_dataset:
                    raise ValueError(
                        "match and resolve topology policies point to different topology datasets"
                    )
                topology_dataset = resolve_capability.target_dataset
                activation_sources.append("resolve")
                if resolve_policy.on_missing_topology == "hard_error":
                    target_failure_is_hard = True
            else:
                return TopologyActivationDecision(
                    request=TopologyBootstrapRequest(
                        pipeline_dataset=dataset_name,
                        topology_dataset=None,
                        run_id="",
                        require_source_topology=False,
                        require_target_topology=False,
                    ),
                    capability_enabled=False,
                    activation_sources=(),
                    target_failure_is_hard=False,
                    skipped_reason="capability_disabled",
                    activation_error=(
                        f"resolve topology_link is enabled for dataset '{dataset_name}', "
                        "but the target topology capability is disabled"
                    ),
                )

        activated = bool(activation_sources)
        return TopologyActivationDecision(
            request=TopologyBootstrapRequest(
                pipeline_dataset=dataset_name,
                topology_dataset=topology_dataset if activated else None,
                run_id="",
                # Phase 1a/1b работают от row-level canonical path и не требуют
                # полного source snapshot. Source builder и его consumer появляются
                # на Stage G+, где флаг будет активироваться по наличию такого consumer,
                # а не по факту включённости match/resolve policy.
                require_source_topology=False,
                require_target_topology=activated,
            ),
            capability_enabled=capability_enabled,
            activation_sources=tuple(activation_sources),
            target_failure_is_hard=target_failure_is_hard,
            skipped_reason=None if activated else "topology_policy_disabled",
        )

    @staticmethod
    def _load_capability(dataset_name: str):
        from connector.domain.dataset_dsl.loader import load_dataset_dsl_spec

        return load_dataset_dsl_spec(dataset_name).topology

    @staticmethod
    def _load_match_policy(dataset_name: str):
        from connector.domain.transform_dsl.compilers.match import MatchDsl

        spec = load_match_spec_for_dataset(dataset_name)
        return MatchDsl().compile(spec).topology

    @staticmethod
    def _load_resolve_policy(dataset_name: str):
        from connector.domain.transform_dsl.compilers.resolve import ResolveDsl

        spec = load_resolve_spec_for_dataset(dataset_name)
        sink_spec = load_sink_spec_for_dataset(dataset_name)
        return ResolveDsl().compile(spec, sink_spec=sink_spec).topology_link

    @classmethod
    def _load_resolve_topology_capability(
        cls,
        *,
        dataset_name: str,
        field: str,
    ) -> "_ResolveTopologyCapability | None":
        from connector.domain.transform_dsl.compilers.resolve import ResolveDsl

        spec = load_resolve_spec_for_dataset(dataset_name)
        sink_spec = load_sink_spec_for_dataset(dataset_name)
        compiled = ResolveDsl().compile(spec, sink_spec=sink_spec)
        for rule in compiled.link_rules.fields:
            if rule.field != field:
                continue
            capability = cls._load_capability(rule.target_dataset)
            return _ResolveTopologyCapability(
                target_dataset=rule.target_dataset,
                capability=capability,
            )
        return None


@dataclass(frozen=True)
class _ResolveTopologyCapability:
    """Связка resolve-side topology policy с целевым dataset capability."""

    target_dataset: str
    capability: Any


class TopologyBootstrapUseCase:
    """Построить target-only topology artifacts и вернуть run-scoped результат."""

    def __init__(
        self,
        *,
        target_usecase_factory: Callable[[Any, Any], TargetTopologyBuildUseCase],
        event_sink: TopologyEventSink,
        topology_loader: Callable[[str], Any] = load_topology_spec_for_dataset,
        compiler: TopologyDsl | None = None,
        built_at_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self._target_usecase_factory = target_usecase_factory
        self._event_sink = event_sink
        self._topology_loader = topology_loader
        self._compiler = compiler or TopologyDsl()
        self._built_at_provider = built_at_provider or _utc_now

    def run(
        self,
        *,
        request: TopologyBootstrapRequest,
        target_failure_is_hard: bool,
    ) -> TopologyBootstrapResult:
        """Выполнить target-only topology bootstrap текущего этапа."""

        resolved_request = _normalized_request(request)
        topology_dataset = (
            resolved_request.topology_dataset or resolved_request.pipeline_dataset
        )
        started_at = time.monotonic()
        self._event_sink.emit(
            level=logging.INFO,
            event="bootstrap.start",
            payload={
                "dataset": resolved_request.pipeline_dataset,
                "topology_dataset": resolved_request.topology_dataset,
                "require_source": resolved_request.require_source_topology,
                "require_target": resolved_request.require_target_topology,
            },
        )
        topology_spec = self._topology_loader(topology_dataset)
        self._event_sink.emit(
            level=logging.INFO,
            event="spec.loaded",
            payload={
                "dataset": topology_spec.dataset,
                "source_mode": topology_spec.topology.source.mode,
                "target_mode": topology_spec.topology.target.mode,
                "path_columns": [
                    item.field for item in topology_spec.topology.source.path_columns
                ],
            },
        )
        compiled = self._compiler.compile(topology_spec)
        self._event_sink.emit(
            level=logging.INFO,
            event="canonicalizer.compiled",
            payload={
                "ops_count": len(compiled.python.ops),
                "ops": [item.op for item in compiled.python.ops],
                "normalization_version": compiled.normalization_version,
            },
        )

        target_result: TargetTopologyBuildResult | None = None
        if resolved_request.require_target_topology:
            target_usecase = self._target_usecase_factory(topology_spec, compiled)
            target_result = target_usecase.build(
                dataset=topology_dataset,
                freshness_policy=_default_freshness_policy(),
                require_target_topology=target_failure_is_hard,
            )
            _emit_target_readiness_events(
                sink=self._event_sink,
                result=target_result,
            )

        artifacts: TopologyRunArtifacts | None = None
        errors: tuple[DiagnosticItem, ...] = ()
        warnings: tuple[DiagnosticItem, ...] = ()

        if target_result is not None:
            errors = tuple(target_result.errors)
            warnings = tuple(target_result.warnings)
            if target_result.readiness.is_ready:
                artifacts = TopologyRunArtifacts(
                    source_snapshot=None,
                    target_snapshot=target_result.snapshot,
                    metadata=TopologyBuildMetadata(
                        dataset_name=topology_dataset,
                        source_file_fingerprint=None,
                        cache_snapshot_revision=(
                            target_result.metadata.cache_snapshot_revision
                        ),
                        built_at=self._built_at_provider(),
                        topology_normalization_version=compiled.normalization_version,
                    ),
                )
                self._event_sink.emit(
                    level=logging.INFO,
                    event="target.build.finish",
                    payload={
                        "node_count": len(target_result.snapshot.nodes_by_id),
                        "root_count": len(target_result.snapshot.roots),
                        "max_depth": max(
                            (
                                target_result.snapshot.depth(node_id)
                                for node_id in target_result.snapshot.nodes_by_id
                            ),
                            default=0,
                        ),
                    },
                )

        duration_ms = int((time.monotonic() - started_at) * 1000)
        self._event_sink.emit(
            level=logging.INFO,
            event="bootstrap.finish",
            payload={
                "duration_ms": duration_ms,
                "built_sides": (
                    ["target"]
                    if artifacts is not None and artifacts.target_snapshot is not None
                    else []
                ),
                "status": _bootstrap_status(errors=errors, warnings=warnings),
                "errors": len(errors),
                "warnings": len(warnings),
            },
        )
        return TopologyBootstrapResult(
            artifacts=artifacts,
            errors=errors,
            warnings=warnings,
        )


def _emit_target_readiness_events(
    *,
    sink: TopologyEventSink,
    result: TargetTopologyBuildResult,
) -> None:
    details = dict(result.readiness.details)
    diagnostics = (*result.readiness.errors, *result.readiness.warnings)
    if result.readiness.errors:
        level = logging.ERROR
    elif result.readiness.warnings:
        level = logging.WARNING
    else:
        level = logging.INFO
    event = "readiness.evaluated"
    if any(item.code == "TOPOLOGY_TARGET_EMPTY" for item in diagnostics):
        event = "readiness.empty"
    elif any(item.code == "TOPOLOGY_TARGET_STALE" for item in diagnostics):
        event = "readiness.stale"
    sink.emit(
        level=level,
        event=event,
        payload={
            "side": "target",
            "is_ready": result.readiness.is_ready,
            "decision": details.get("decision"),
            "freshness_present": details.get("freshness_present"),
            "reason": details.get("reason"),
            "cache_snapshot_revision": details.get("cache_snapshot_revision"),
            "age_seconds": details.get("age_seconds"),
            "max_age_seconds": details.get("max_age_seconds"),
        },
    )


def _bootstrap_status(
    *,
    errors: tuple[DiagnosticItem, ...],
    warnings: tuple[DiagnosticItem, ...],
) -> str:
    if errors:
        return "error"
    if warnings:
        return "warn"
    return "ok"


def _default_freshness_policy():
    from connector.domain.ports.topology import TopologyFreshnessPolicy

    return TopologyFreshnessPolicy(mode="none")


def _normalized_request(request: TopologyBootstrapRequest) -> TopologyBootstrapRequest:
    topology_dataset = request.topology_dataset or request.pipeline_dataset
    return TopologyBootstrapRequest(
        pipeline_dataset=request.pipeline_dataset,
        topology_dataset=topology_dataset,
        run_id=request.run_id,
        require_source_topology=request.require_source_topology,
        require_target_topology=request.require_target_topology,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)
