"""
Назначение:
    Единая доменная граница доступа к cache-возможностям.
"""

from __future__ import annotations

from typing import Any, ContextManager, Protocol

from connector.domain.ports.cache.pending_links import PendingLink, PendingRow
from connector.domain.ports.cache.repository import CacheMeta, UpsertResult


class CacheGatewayPort(Protocol):
    """
    Назначение/ответственность:
        Единый порт cache boundary для transform/planning/apply/cache use-cases.

    Примечание:
        Детали хранения (snapshot/identity/pending) остаются внутренними для infra.
    """

    # Snapshot/cache operations
    def transaction(self) -> ContextManager[None]: ...
    def upsert(self, dataset: str, write_model: dict) -> UpsertResult: ...
    def count(self, dataset: str) -> int: ...
    def count_by_table(self, dataset: str) -> dict[str, int]: ...
    def clear(self, dataset: str) -> None: ...
    def list_datasets(self) -> list[str]: ...
    def get_meta(self, dataset: str | None = None) -> CacheMeta: ...
    def set_meta(self, dataset: str | None, key: str, value: str | None) -> None: ...
    def reset_meta(self, dataset: str) -> None: ...
    def find(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> list[dict]: ...
    def find_one(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> dict | None: ...

    # Identity operations
    def upsert_identity(self, dataset: str, identity_key: str, resolved_id: str) -> None: ...
    def find_candidates(self, dataset: str, identity_key: str) -> list[str]: ...
    def set_runtime_state(
        self,
        scope: str,
        dataset: str,
        state_key: str,
        state_value: str,
    ) -> None: ...
    def get_runtime_state(
        self,
        scope: str,
        dataset: str,
        state_key: str,
    ) -> str | None: ...
    def clear_runtime_scope(self, scope: str) -> None: ...

    # Pending operations
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
