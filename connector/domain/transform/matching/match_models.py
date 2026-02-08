"""
Назначение:
    Модели матчинга и результатов сопоставления.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from connector.domain.models import Identity, RowRef


class ResolveOp:
    """
    Назначение:
        Тип операции для resolver.
    """

    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"
    CONFLICT = "conflict"


class MatchDecisionReason:
    """
    Назначение:
        Канонические reason-коды для explainability match-решения.
    """

    IDENTITY_EXACT = "identity_exact"
    IDENTITY_NOT_FOUND = "identity_not_found"

    FUZZY_NO_CANDIDATES = "fuzzy_no_candidates"
    FUZZY_NO_RANKED = "fuzzy_no_ranked"
    FUZZY_TIE = "fuzzy_tie"
    FUZZY_ACCEPT = "fuzzy_accept"
    FUZZY_REVIEW = "fuzzy_review"
    FUZZY_REJECT = "fuzzy_reject"


class MatchDecisionStatus(str, Enum):
    """
    Назначение:
        Типизированные статусы решения матчинга (переходный контракт до DSL).
    """

    MATCHED = "matched"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    CONFLICT_SOURCE = "conflict_source"


@dataclass(frozen=True)
class MatchCandidate:
    """
    Назначение:
        Каноническое представление кандидата в match-решении.
    """

    target_id: str | None
    identity: str | None
    score: float | None
    match_mode: str
    evidence: dict[str, Any] | None = None


@dataclass(frozen=True)
class MatchDecision:
    """
    Назначение:
        Типизированное решение матчера без привязки к legacy-статусам.
    """

    status: MatchDecisionStatus
    reason_code: str
    message: str | None = None
    selected: MatchCandidate | None = None
    candidates: tuple[MatchCandidate, ...] = ()
    score: float | None = None
    meta: dict[str, Any] = field(default_factory=dict)


def resolve_decision_status(row: "MatchedRow") -> MatchDecisionStatus:
    """
    Назначение:
        Вернуть typed-статус решения для downstream стадий.
    """
    return row.match_decision.status


@dataclass(frozen=True)
class MatchedRow:
    """
    Назначение:
        Результат сопоставления одной строки (matcher output).
    """

    row_ref: RowRef
    identity: Identity
    desired_state: dict[str, Any]
    existing: dict[str, Any] | None
    fingerprint: str
    fingerprint_fields: tuple[str, ...]
    match_decision: MatchDecision
    source_links: dict[str, Identity] = field(default_factory=dict)
    target_id: str | None = None


@dataclass(frozen=True)
class ResolvedRow:
    """
    Назначение:
        Результат разрешения операции (resolver output).
    """

    row_ref: RowRef
    identity: Identity
    op: str
    desired_state: dict[str, Any]
    existing: dict[str, Any] | None = None
    changes: dict[str, Any] = field(default_factory=dict)
    target_id: str | None = None
    source_ref: dict[str, Any] | None = None
    secret_fields: list[str] = field(default_factory=list)


def build_fingerprint(
    desired_state: dict[str, Any],
    *,
    ignored_fields: set[str] | None = None,
) -> tuple[str, tuple[str, ...]]:
    """
    Назначение:
        Построить fingerprint по желаемому состоянию с учётом исключённых полей.
    Контракт:
        Возвращает (hash, fields), где fields — список ключей, участвующих в hash.
    """
    ignored = ignored_fields or set()
    payload = {key: value for key, value in desired_state.items() if key not in ignored}
    fingerprint = _hash_payload(payload)
    return fingerprint, tuple(sorted(payload.keys()))


def build_fingerprint_for_keys(
    payload: dict[str, Any] | None,
    keys: tuple[str, ...],
) -> str:
    """
    Назначение:
        Построить fingerprint по конкретному набору ключей (для existing).
    """
    if not payload:
        payload = {}
    subset = {key: payload.get(key) for key in keys}
    return _hash_payload(subset)


def _hash_payload(payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, default=str)
    return hashlib.md5(serialized.encode("utf-8")).hexdigest()
