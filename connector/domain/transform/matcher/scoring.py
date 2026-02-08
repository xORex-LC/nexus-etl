"""
Назначение:
    Утилиты fuzzy scoring для match-стадии.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from connector.domain.transform.common import normalize_for_compare


@dataclass(frozen=True)
class CandidateScore:
    """
    Назначение:
        Итоговый score кандидата target.
    """

    candidate: dict[str, Any]
    score: float


def score_candidate(
    source_values: dict[str, Any],
    candidate_values: dict[str, Any],
    *,
    comparators: dict[str, str],
    weights: dict[str, float],
    score_round: int = 4,
) -> float:
    """
    Назначение:
        Рассчитать агрегированный weighted score кандидата.
    """
    if not comparators and not weights:
        return 0.0

    fields = set(comparators.keys()) | set(weights.keys())
    weighted_sum = 0.0
    total_weight = 0.0

    for field in fields:
        comparator = comparators.get(field, "exact")
        weight = max(0.0, float(weights.get(field, 1.0)))
        if weight == 0.0:
            continue
        source = source_values.get(field)
        candidate = candidate_values.get(field)
        weighted_sum += weight * _field_score(source, candidate, comparator=comparator)
        total_weight += weight

    if total_weight <= 0.0:
        return 0.0
    return round(weighted_sum / total_weight, max(0, score_round))


def rank_candidates(
    source_values: dict[str, Any],
    candidates: list[dict[str, Any]],
    *,
    comparators: dict[str, str],
    weights: dict[str, float],
    score_round: int = 4,
) -> list[CandidateScore]:
    """
    Назначение:
        Отсортировать кандидатов по score (по убыванию).
    """
    ranked = [
        CandidateScore(
            candidate=candidate,
            score=score_candidate(
                source_values,
                candidate,
                comparators=comparators,
                weights=weights,
                score_round=score_round,
            ),
        )
        for candidate in candidates
    ]
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def is_tie(ranked: list[CandidateScore], *, tie_delta: float) -> bool:
    """
    Назначение:
        Определить неразрешимую близость top1/top2.
    """
    if len(ranked) < 2:
        return False
    return (ranked[0].score - ranked[1].score) < max(0.0, tie_delta)


def _field_score(source: Any, candidate: Any, *, comparator: str) -> float:
    if source is None or candidate is None:
        return 0.0

    left = str(source)
    right = str(candidate)
    mode = (comparator or "exact").strip().lower()

    if mode == "exact":
        return 1.0 if left == right else 0.0
    if mode == "casefold":
        return 1.0 if normalize_for_compare(left) == normalize_for_compare(right) else 0.0
    if mode == "similarity":
        return SequenceMatcher(
            None,
            normalize_for_compare(left),
            normalize_for_compare(right),
        ).ratio()

    # Unknown comparator -> conservative exact fallback.
    return 1.0 if left == right else 0.0
