from __future__ import annotations

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
