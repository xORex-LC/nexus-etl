"""
Назначение:
    Role-based cache контракты для stage/use-case слоёв.
"""

from __future__ import annotations

from typing import Any, ContextManager, Protocol

from connector.domain.ports.cache.models import CacheMeta, PendingLink, PendingRow, UpsertResult


class CacheAdminPort(Protocol):
    """
    Назначение:
        Администрирование и snapshot-операции кэша (refresh/status/clear path).
    """

    def transaction(self) -> ContextManager[None]: ...
    def upsert(self, dataset: str, write_model: dict) -> UpsertResult: ...
    def count(self, dataset: str) -> int: ...
    def count_by_table(self, dataset: str) -> dict[str, int]: ...
    def clear(self, dataset: str) -> None: ...
    def list_datasets(self) -> list[str]: ...
    def get_meta(self, dataset: str | None = None) -> CacheMeta: ...
    def set_meta(self, dataset: str | None, key: str, value: str | None) -> None: ...
    def reset_meta(self, dataset: str) -> None: ...


class EnrichLookupPort(Protocol):
    """
    Назначение:
        Lookup/exists операции enrich-стадии.
    """

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


class MatchRuntimePort(Protocol):
    """
    Назначение:
        Контракт runtime состояния и lookup для matcher.
    """

    def find(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> list[dict]: ...

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


class ResolveRuntimePort(Protocol):
    """
    Назначение:
        Контракт resolve-стадии для identity/pending lifecycle.
    """

    def find_candidates(self, dataset: str, identity_key: str) -> list[str]: ...

    def add_pending(
        self,
        dataset: str,
        source_row_id: str,
        field: str,
        lookup_key: str,
        expires_at: str | None,
        payload: str | None = None,
    ) -> int: ...

    def list_pending_rows(self, dataset: str) -> list[PendingRow]: ...
    def mark_resolved_for_source(self, source_row_id: str) -> None: ...
    def mark_conflict(self, pending_id: int, reason: str | None = None) -> None: ...
    def touch_attempt(self, pending_id: int) -> int: ...
    def sweep_expired(self, now: str, *, reason: str | None = None) -> list[PendingLink]: ...
    def purge_stale(
        self,
        cutoff: str,
        statuses: tuple[str, ...] | None = None,
    ) -> int: ...


class ApplyRuntimePort(Protocol):
    """
    Назначение:
        Пост-apply синхронизация identity/pending.
    """

    def upsert_identity(self, dataset: str, identity_key: str, resolved_id: str) -> None: ...
    def list_pending_for_key(self, dataset: str, lookup_key: str) -> list[PendingLink]: ...
    def mark_resolved(self, pending_id: int) -> None: ...


class CacheRefreshPort(CacheAdminPort, ApplyRuntimePort, Protocol):
    """
    Назначение:
        Минимальный контракт для cache-refresh (snapshot + post-sync).
    """


class PendingReplayPort(ResolveRuntimePort, Protocol):
    """
        Назначение:
        Контракт для replay pending rows в import-plan path.
    """


class PlanningRuntimePort(MatchRuntimePort, ResolveRuntimePort, Protocol):
    """
    Назначение:
        Контракт cache gateway для связки match+resolve.
    """
