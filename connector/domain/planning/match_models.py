from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from connector.domain.models import Identity, MatchStatus, RowRef


class ResolveOp:
    """
    Назначение:
        Тип операции для resolver.
    """

    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"
    CONFLICT = "conflict"


@dataclass(frozen=True)
class MatchedRow:
    """
    Назначение:
        Результат сопоставления одной строки (matcher output).
    """

    row_ref: RowRef
    identity: Identity
    match_status: MatchStatus
    desired_state: dict[str, Any]
    existing: dict[str, Any] | None
    fingerprint: str
    fingerprint_fields: tuple[str, ...]
    source_links: dict[str, Identity] = field(default_factory=dict)
    resource_id: str | None = None


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
    resource_id: str | None = None
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
