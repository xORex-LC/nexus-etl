"""
Назначение:
    Разрешение конфликтов и merge-политики для enrich.
"""

from __future__ import annotations

from typing import Any

from connector.domain.transform.enrich.models import CandidateDecision, CandidateValue, MergeMode, MergePolicy


class _FieldMutationTracker:
    """
    Отслеживание конфликтов между операциями по одному полю.
    """

    def __init__(self) -> None:
        self._writers: dict[str, str] = {}

    def has_writer(self, field: str) -> bool:
        return field in self._writers

    def register(self, field: str, op_name: str) -> None:
        self._writers[field] = op_name

    def last_writer(self, field: str) -> str | None:
        return self._writers.get(field)


class ConflictResolver:
    """
    Разрешение конфликтов между кандидатами.
    """

    def decide(self, candidates: list[CandidateValue]) -> CandidateDecision:
        if not candidates:
            return CandidateDecision(status="NONE", selected=None, candidates=[], reason="no_candidates")
        if len(candidates) == 1:
            return CandidateDecision(status="SELECTED", selected=candidates[0], candidates=candidates)
        sorted_candidates = sorted(
            candidates,
            key=lambda cand: (
                -((cand.priority if cand.priority is not None else 0)),
                -(cand.confidence or 0.0),
            ),
        )
        top = sorted_candidates[0]
        if len(sorted_candidates) > 1:
            second = sorted_candidates[1]
            if top.priority == second.priority and (top.confidence or 0.0) == (second.confidence or 0.0):
                return CandidateDecision(status="AMBIGUOUS", selected=None, candidates=sorted_candidates)
        return CandidateDecision(status="SELECTED", selected=top, candidates=sorted_candidates)


class MergeEngine:
    """
    Применение merge-политики к полю.
    """

    def __init__(self, authoritative_sources: set[str]) -> None:
        self.authoritative_sources = authoritative_sources

    def should_apply(self, current: Any, candidate: CandidateValue, policy: MergePolicy) -> bool:
        handlers = {
            MergeMode.RECOMPUTE_ALWAYS: lambda: True,
            MergeMode.NEVER_OVERRIDE: lambda: False,
            MergeMode.OVERRIDE_IF_AUTHORITATIVE: lambda: candidate.source in self.authoritative_sources,
            MergeMode.OVERRIDE_IF_EMPTY: lambda: current is None or current == "",
        }
        handler = handlers.get(policy.mode, handlers[MergeMode.OVERRIDE_IF_EMPTY])
        return handler()
