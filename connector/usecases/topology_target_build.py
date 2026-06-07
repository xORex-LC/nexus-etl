"""Use case target topology build — orchestration read → build → readiness

Связывает cache-backed read seam, target hierarchy builder и readiness evaluator
в один узкий сценарий Stage C. Этот use case не знает о CLI/DI/bootstrap steps и
не тянет за собой stage consumers.

Зона ответственности:
    - Выполнить target-side topology path от cache rows до validated snapshot-а
    - Объединить build diagnostics и readiness outcome в один typed result

Вне области ответственности:
    - Source topology bootstrap
    - Pre-handler activation logic и report/log wiring
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from connector.domain.dependency_tree import TopologySnapshot
from connector.domain.dependency_tree.readiness import TopologyTargetReadinessEvaluator
from connector.domain.models import DiagnosticItem
from connector.domain.ports.topology import (
    TargetHierarchyReadMeta,
    TargetHierarchyTopologyBuilderPort,
    TopologyFreshnessPolicy,
    TopologyTargetReadPort,
    TopologyTargetReadinessResult,
)


@dataclass(frozen=True)
class TargetTopologyBuildResult:
    """Итог target-side topology build path без runtime wiring"""

    snapshot: TopologySnapshot
    metadata: TargetHierarchyReadMeta
    readiness: TopologyTargetReadinessResult

    @property
    def errors(self) -> tuple[DiagnosticItem, ...]:
        return self.readiness.errors

    @property
    def warnings(self) -> tuple[DiagnosticItem, ...]:
        return self.readiness.warnings


class TargetTopologyBuildUseCase:
    """Построить target topology snapshot и сразу оценить его readiness"""

    def __init__(
        self,
        *,
        reader: TopologyTargetReadPort,
        builder: TargetHierarchyTopologyBuilderPort,
        readiness_evaluator: TopologyTargetReadinessEvaluator,
    ) -> None:
        self._reader = reader
        self._builder = builder
        self._readiness_evaluator = readiness_evaluator

    def build(
        self,
        *,
        dataset: str,
        freshness_policy: TopologyFreshnessPolicy,
        require_target_topology: bool,
        now: datetime | None = None,
    ) -> TargetTopologyBuildResult:
        """Собрать target snapshot из read seam и вернуть readiness outcome"""

        metadata = self._reader.read_snapshot_metadata(dataset)
        snapshot, build_errors, build_warnings = self._builder.build(
            self._reader.read_hierarchy(dataset)
        )
        if build_errors or build_warnings:
            return TargetTopologyBuildResult(
                snapshot=snapshot,
                metadata=metadata,
                readiness=TopologyTargetReadinessResult(
                    is_ready=False,
                    errors=build_errors,
                    warnings=build_warnings,
                    details={
                        "decision": (
                            "required_failure"
                            if require_target_topology
                            else "optional_skip"
                        ),
                        "reason": "builder_validation_failed",
                        "policy_mode": freshness_policy.mode,
                        "require_target_topology": require_target_topology,
                        "row_count": metadata.row_count,
                        "cache_snapshot_revision": metadata.cache_snapshot_revision,
                        "refreshed_at": (
                            metadata.refreshed_at.isoformat()
                            if metadata.refreshed_at is not None
                            else None
                        ),
                    },
                ),
            )

        readiness = self._readiness_evaluator.evaluate(
            snapshot=snapshot,
            metadata=metadata,
            policy=freshness_policy,
            require_target_topology=require_target_topology,
            now=now,
        )
        return TargetTopologyBuildResult(
            snapshot=snapshot,
            metadata=metadata,
            readiness=readiness,
        )
