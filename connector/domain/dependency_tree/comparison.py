"""Topology comparison core — общий explainable ladder поверх read-only snapshot queries.

Модуль содержит storage-agnostic алгоритм topology-сравнения для stage-level
consumer-ов. Он сопоставляет row-level source locator с наборами target node id
через явную comparison ladder, а не через один непрозрачный fingerprint.

Responsibilities:
    - Определять типизированные topology match modes для runtime consumer-ов
    - Сравнивать target candidates только через `TopologyQueryPort`
    - Возвращать explainable evidence для reporting и downstream policy

Out of scope:
    - Построение source locator из raw source row
    - Чтение topology snapshot-ов из runtime provider-ов
    - Orchestration match/resolve стадий и diagnostics policy
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Mapping

from connector.domain.dependency_tree.snapshot import TopologyQueryPort


class TopologyMatchMode(str, Enum):
    """Типизированные рунги topology comparison ladder для stage-facing consumer-ов."""

    EXACT_CANONICAL_PATH = "exact_canonical_path"
    EXACT_LEAF_PARENT_CHAIN = "exact_leaf_parent_chain"
    EXACT_LEAF_ROOT_DEPTH = "exact_leaf_root_depth"
    AMBIGUOUS = "ambiguous"
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class TopologyComparisonResult:
    """Explainable результат общего topology comparison core."""

    matched_candidate_ids: tuple[str, ...]
    mode: TopologyMatchMode
    reason: str | None
    evidence: Mapping[str, Any]

    @property
    def is_ambiguous(self) -> bool:
        return self.mode == TopologyMatchMode.AMBIGUOUS

    @property
    def matched_candidate_id(self) -> str | None:
        if len(self.matched_candidate_ids) != 1:
            return None
        return self.matched_candidate_ids[0]


def compare_topology_candidates(
    *,
    snapshot: TopologyQueryPort,
    source_segments: tuple[str, ...],
    candidate_ids: Iterable[str],
    ladder: tuple[TopologyMatchMode, ...],
) -> TopologyComparisonResult:
    """Сравнить source locator и target candidates через заданную comparison ladder.

    Args:
        snapshot: Read-only topology query port для candidate lookup.
        source_segments: Canonicalized source hierarchy path.
        candidate_ids: Candidate topology node ids для сравнения.
        ladder: Упорядоченный список рунгов от strongest к weakest.

    Returns:
        Explainable comparison result с matched ids, final mode и evidence.
    """

    normalized_candidates = tuple(dict.fromkeys(str(candidate_id) for candidate_id in candidate_ids))
    rung_results: list[dict[str, Any]] = []

    if not source_segments or not normalized_candidates:
        return TopologyComparisonResult(
            matched_candidate_ids=(),
            mode=TopologyMatchMode.NO_MATCH,
            reason="empty_source_or_candidates",
            evidence={
                "source_segments": list(source_segments),
                "candidate_ids": list(normalized_candidates),
                "rungs": tuple(),
            },
        )

    for mode in ladder:
        matched_ids = _match_candidates_for_mode(
            snapshot=snapshot,
            source_segments=source_segments,
            candidate_ids=normalized_candidates,
            mode=mode,
        )
        rung_results.append(
            {
                "mode": mode.value,
                "matched_candidate_ids": list(matched_ids),
                "matched_count": len(matched_ids),
            }
        )
        if len(matched_ids) == 1:
            return TopologyComparisonResult(
                matched_candidate_ids=matched_ids,
                mode=mode,
                reason=f"resolved_by_{mode.value}",
                evidence={
                    "source_segments": list(source_segments),
                    "candidate_ids": list(normalized_candidates),
                    "rungs": tuple(rung_results),
                },
            )
        if len(matched_ids) > 1:
            return TopologyComparisonResult(
                matched_candidate_ids=matched_ids,
                mode=TopologyMatchMode.AMBIGUOUS,
                reason=f"ambiguous_on_{mode.value}",
                evidence={
                    "source_segments": list(source_segments),
                    "candidate_ids": list(normalized_candidates),
                    "rungs": tuple(rung_results),
                },
            )

    return TopologyComparisonResult(
        matched_candidate_ids=(),
        mode=TopologyMatchMode.NO_MATCH,
        reason="no_topology_confirmation",
        evidence={
            "source_segments": list(source_segments),
            "candidate_ids": list(normalized_candidates),
            "rungs": tuple(rung_results),
        },
    )


def _match_candidates_for_mode(
    *,
    snapshot: TopologyQueryPort,
    source_segments: tuple[str, ...],
    candidate_ids: tuple[str, ...],
    mode: TopologyMatchMode,
) -> tuple[str, ...]:
    matched: list[str] = []
    for candidate_id in candidate_ids:
        if _candidate_matches_mode(
            snapshot=snapshot,
            source_segments=source_segments,
            candidate_id=candidate_id,
            mode=mode,
        ):
            matched.append(candidate_id)
    return tuple(matched)


def _candidate_matches_mode(
    *,
    snapshot: TopologyQueryPort,
    source_segments: tuple[str, ...],
    candidate_id: str,
    mode: TopologyMatchMode,
) -> bool:
    candidate_path = snapshot.canonical_path(candidate_id)
    if mode == TopologyMatchMode.EXACT_CANONICAL_PATH:
        return candidate_path == source_segments

    if mode == TopologyMatchMode.EXACT_LEAF_PARENT_CHAIN:
        if len(source_segments) < 2 or len(candidate_path) < 2:
            return False
        return candidate_path[-2:] == source_segments[-2:]

    if mode == TopologyMatchMode.EXACT_LEAF_ROOT_DEPTH:
        if not source_segments or not candidate_path:
            return False
        return (
            candidate_path[-1] == source_segments[-1]
            and candidate_path[0] == source_segments[0]
            and len(candidate_path) == len(source_segments)
        )

    return False
