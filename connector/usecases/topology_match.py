"""Topology match consumer — row-level locator builder и match refinement service.

Модуль содержит выделенный topology-aware consumer для match-стадии. Он
преобразует raw source rows в canonical topology locator-ы и адаптирует общий
comparison core к контракту `TopologyMatchServicePort`.

Responsibilities:
    - Строить row-level source topology locator из `SourceRecord`
    - Адаптировать shared topology comparison core к match-stage contract

Out of scope:
    - Match candidate discovery и fuzzy scoring
    - Runtime bootstrap/provider wiring
    - Resolve-side propagation topology-derived links
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from connector.domain.dependency_tree import (
    TopologyQueryPort,
    compare_topology_candidates,
)
from connector.domain.ports.topology import (
    SourceTopologyCanonicalPath,
    SourceTopologyLocatorBuilderPort,
    TopologyMatchResult,
    TopologyMatchServicePort,
)
from connector.domain.transform.common import CompiledCanonicalizer
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform_dsl.compilers.match import TopologyMatchPolicy


@dataclass(frozen=True)
class SourceTopologyLocatorBuilder(SourceTopologyLocatorBuilderPort):
    """Построить canonical source locator из настроенных raw source path columns."""

    path_fields: tuple[str, ...]
    canonicalizer: CompiledCanonicalizer

    def build(self, record: SourceRecord) -> SourceTopologyCanonicalPath | None:
        raw_segments = tuple(record.values.get(field) for field in self.path_fields)
        canonical_segments = self.canonicalizer.canonicalize_segments(
            tuple("" if value is None else str(value) for value in raw_segments)
        )
        normalized_segments = tuple(
            segment for segment in canonical_segments if segment.strip()
        )
        if not normalized_segments:
            return None
        return SourceTopologyCanonicalPath(canonical_segments=normalized_segments)


@dataclass(frozen=True)
class TopologyMatchService(TopologyMatchServicePort):
    """Применить compiled topology ladder к candidate ids на match-стадии."""

    snapshot: TopologyQueryPort
    policy: TopologyMatchPolicy

    def compare(
        self,
        source_locator: SourceTopologyCanonicalPath,
        target_candidate_ids: tuple[str, ...],
    ) -> TopologyMatchResult:
        comparison = compare_topology_candidates(
            snapshot=self.snapshot,
            source_segments=source_locator.canonical_segments,
            candidate_ids=target_candidate_ids,
            ladder=self.policy.comparison_ladder,
        )
        return TopologyMatchResult(
            matched_target_id=comparison.matched_candidate_id,
            is_ambiguous=comparison.is_ambiguous,
            mode=comparison.mode,
            reason=comparison.reason,
            evidence=comparison.evidence,
        )


def build_topology_match_service(
    *,
    snapshot: TopologyQueryPort | None,
    policy: TopologyMatchPolicy | None,
) -> TopologyMatchServicePort | None:
    """Собрать конкретный match-service только когда topology runtime пригоден."""

    if snapshot is None or policy is None or not policy.enabled:
        return None
    return TopologyMatchService(snapshot=snapshot, policy=policy)


def build_source_locator_builder(
    *,
    path_fields: Iterable[str],
    canonicalizer: CompiledCanonicalizer | None,
) -> SourceTopologyLocatorBuilderPort | None:
    """Собрать row-level source locator builder при наличии topology canonicalization."""

    if canonicalizer is None:
        return None
    resolved_fields = tuple(str(field) for field in path_fields if str(field).strip())
    if not resolved_fields:
        return None
    return SourceTopologyLocatorBuilder(
        path_fields=resolved_fields,
        canonicalizer=canonicalizer,
    )
