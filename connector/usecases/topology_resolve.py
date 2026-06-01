"""Topology resolve consumer — FK disambiguation поверх shared comparison core.

Модуль адаптирует общий topology comparison core к resolve-side write path.
Он не знает про pending lifecycle и не материализует payload сам: его задача
только интерпретировать row-level source locator против набора target candidate ids
и вернуть типизированный результат для `ResolveCore`.
"""

from __future__ import annotations

from dataclasses import dataclass

from connector.domain.dependency_tree import (
    TopologyQueryPort,
    compare_topology_candidates,
)
from connector.domain.ports.topology import (
    SourceTopologyCanonicalPath,
    TopologyLinkResolutionResult,
    TopologyLinkResolutionServicePort,
)
from connector.domain.transform_dsl.compilers.resolve import (
    ResolveTopologyLinkPolicy,
)


@dataclass(frozen=True)
class TopologyLinkResolutionService(TopologyLinkResolutionServicePort):
    """Применить compiled topology ladder к link-candidate ids на resolve-стадии."""

    snapshot: TopologyQueryPort
    policy: ResolveTopologyLinkPolicy

    def resolve_link(
        self,
        *,
        field: str,
        source_locator: SourceTopologyCanonicalPath,
        target_candidate_ids: tuple[str, ...],
    ) -> TopologyLinkResolutionResult:
        comparison = compare_topology_candidates(
            snapshot=self.snapshot,
            source_segments=source_locator.canonical_segments,
            candidate_ids=target_candidate_ids,
            ladder=self.policy.comparison_ladder,
        )
        return TopologyLinkResolutionResult(
            resolved_field=field,
            resolved_target_id=comparison.matched_candidate_id,
            is_pending=False,
            is_ambiguous=comparison.is_ambiguous,
            mode=comparison.mode,
            reason=comparison.reason,
            evidence=comparison.evidence,
        )


def build_topology_link_resolution_service(
    *,
    snapshot: TopologyQueryPort | None,
    policy: ResolveTopologyLinkPolicy | None,
) -> TopologyLinkResolutionServicePort | None:
    """Собрать resolve-service только когда topology runtime пригоден."""

    if snapshot is None or policy is None or not policy.enabled:
        return None
    return TopologyLinkResolutionService(snapshot=snapshot, policy=policy)
