from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any

from connector.domain.ports.cache.models import CacheMeta, PendingLink, PendingRow, UpsertResult
from connector.infra.cache.identity_repository import SqliteIdentityRepository
from connector.infra.cache.pending_links_repository import SqlitePendingLinksRepository
from connector.infra.cache.repository import SqliteCacheRepository


class SqliteCacheGateway:
    """
    Назначение:
        Единый SQLite фасад для cache/identity/pending операций.
    """

    def __init__(
        self,
        *,
        cache_repo: SqliteCacheRepository,
        identity_repo: SqliteIdentityRepository,
        pending_repo: SqlitePendingLinksRepository,
    ) -> None:
        self._cache_repo = cache_repo
        self._identity_repo = identity_repo
        self._pending_repo = pending_repo

    # Cache admin + lookup
    def transaction(self) -> AbstractContextManager[None]:
        return self._cache_repo.transaction()

    def upsert(self, dataset: str, write_model: dict) -> UpsertResult:
        return self._cache_repo.upsert(dataset, write_model)

    def count(self, dataset: str) -> int:
        return self._cache_repo.count(dataset)

    def count_by_table(self, dataset: str) -> dict[str, int]:
        return self._cache_repo.count_by_table(dataset)

    def clear(self, dataset: str) -> None:
        self._cache_repo.clear(dataset)

    def list_datasets(self) -> list[str]:
        return self._cache_repo.list_datasets()

    def get_meta(self, dataset: str | None = None) -> CacheMeta:
        return self._cache_repo.get_meta(dataset)

    def set_meta(self, dataset: str | None, key: str, value: str | None) -> None:
        self._cache_repo.set_meta(dataset, key, value)

    def reset_meta(self, dataset: str) -> None:
        self._cache_repo.reset_meta(dataset)

    def find(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> list[dict]:
        return self._cache_repo.find(
            dataset,
            filters,
            include_deleted=include_deleted,
            mode=mode,
        )

    def find_one(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> dict | None:
        return self._cache_repo.find_one(
            dataset,
            filters,
            include_deleted=include_deleted,
            mode=mode,
        )

    # Identity/runtime state
    def upsert_identity(self, dataset: str, identity_key: str, resolved_id: str) -> None:
        self._identity_repo.upsert_identity(dataset, identity_key, resolved_id)

    def find_candidates(self, dataset: str, identity_key: str) -> list[str]:
        return self._identity_repo.find_candidates(dataset, identity_key)

    def set_runtime_state(
        self,
        scope: str,
        dataset: str,
        state_key: str,
        state_value: str,
    ) -> None:
        self._identity_repo.set_runtime_state(scope, dataset, state_key, state_value)

    def get_runtime_state(
        self,
        scope: str,
        dataset: str,
        state_key: str,
    ) -> str | None:
        return self._identity_repo.get_runtime_state(scope, dataset, state_key)

    def clear_runtime_scope(self, scope: str) -> None:
        self._identity_repo.clear_runtime_scope(scope)

    # Pending lifecycle
    def add_pending(
        self,
        dataset: str,
        source_row_id: str,
        field: str,
        lookup_key: str,
        expires_at: str | None,
        payload: str | None = None,
    ) -> int:
        return self._pending_repo.add_pending(
            dataset,
            source_row_id,
            field,
            lookup_key,
            expires_at,
            payload,
        )

    def list_pending_for_key(self, dataset: str, lookup_key: str) -> list[PendingLink]:
        return self._pending_repo.list_pending_for_key(dataset, lookup_key)

    def list_pending_rows(self, dataset: str) -> list[PendingRow]:
        return self._pending_repo.list_pending_rows(dataset)

    def mark_resolved(self, pending_id: int) -> None:
        self._pending_repo.mark_resolved(pending_id)

    def mark_resolved_for_source(self, source_row_id: str) -> None:
        self._pending_repo.mark_resolved_for_source(source_row_id)

    def mark_conflict(self, pending_id: int, reason: str | None = None) -> None:
        self._pending_repo.mark_conflict(pending_id, reason)

    def mark_expired(self, pending_id: int, reason: str | None = None) -> None:
        self._pending_repo.mark_expired(pending_id, reason)

    def touch_attempt(self, pending_id: int) -> int:
        return self._pending_repo.touch_attempt(pending_id)

    def sweep_expired(self, now: str, *, reason: str | None = None) -> list[PendingLink]:
        return self._pending_repo.sweep_expired(now, reason=reason)

    def purge_stale(
        self,
        cutoff: str,
        statuses: tuple[str, ...] | None = None,
    ) -> int:
        return self._pending_repo.purge_stale(cutoff, statuses=statuses)
