from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class PendingStatus(str, Enum):
    """
    Назначение:
        Состояние pending-ссылки.
    """

    PENDING = "pending"
    RESOLVED = "resolved"
    CONFLICT = "conflict"
    EXPIRED = "expired"


@dataclass(frozen=True)
class PendingLink:
    """
    Назначение:
        DTO для pending-ссылок.
    """

    pending_id: int
    dataset: str
    source_row_id: str
    field: str
    lookup_key: str
    status: str
    attempts: int
    created_at: str | None
    last_attempt_at: str | None
    expires_at: str | None
    reason: str | None
    payload: str | None


@dataclass(frozen=True)
class PendingRow:
    """
    Назначение:
        Снимок строки для re-resolve.
    """

    dataset: str
    source_row_id: str
    payload: str


class PendingLinksRepository(Protocol):
    """
    Назначение/ответственность:
        Доступ к pending_links (ожидающие резолва ссылки).
    """

    def add_pending(
        self,
        dataset: str,
        source_row_id: str,
        field: str,
        lookup_key: str,
        expires_at: str | None,
        payload: str | None = None,
    ) -> int: ...

    def list_pending_for_key(self, dataset: str, lookup_key: str) -> list[PendingLink]: ...

    def list_pending_rows(self, dataset: str) -> list[PendingRow]: ...

    def mark_resolved(self, pending_id: int) -> None: ...

    def mark_resolved_for_source(self, source_row_id: str) -> None: ...

    def mark_conflict(self, pending_id: int, reason: str | None = None) -> None: ...

    def mark_expired(self, pending_id: int, reason: str | None = None) -> None: ...

    def touch_attempt(self, pending_id: int) -> int: ...

    def sweep_expired(self, now: str, *, reason: str | None = None) -> list[PendingLink]: ...

    def purge_stale(
        self,
        cutoff: str,
        statuses: tuple[str, ...] | None = None,
    ) -> int: ...
