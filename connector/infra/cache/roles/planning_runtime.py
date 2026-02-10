from __future__ import annotations

from typing import Any

from connector.domain.ports.cache.roles import PendingReplayPort, PlanningRuntimePort
from connector.infra.cache.cache_gateway import SqliteCacheGateway


class SqlitePlanningRuntimeAdapter(PlanningRuntimePort, PendingReplayPort):
    """
    Role adapter для связки match+resolve и pending replay.
    """

    def __init__(self, gateway: SqliteCacheGateway) -> None:
        self._gateway = gateway

    # MatchRuntimePort + EnrichLookupPort
    def find(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> list[dict]:
        return self._gateway.cache.find(dataset, filters, include_deleted=include_deleted, mode=mode)

    def find_one(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> dict | None:
        return self._gateway.cache.find_one(dataset, filters, include_deleted=include_deleted, mode=mode)

    def set_runtime_state(
        self,
        scope: str,
        dataset: str,
        state_key: str,
        state_value: str,
    ) -> None:
        self._gateway.identity.set_runtime_state(scope, dataset, state_key, state_value)

    def get_runtime_state(
        self,
        scope: str,
        dataset: str,
        state_key: str,
    ) -> str | None:
        return self._gateway.identity.get_runtime_state(scope, dataset, state_key)

    def clear_runtime_scope(self, scope: str) -> None:
        self._gateway.identity.clear_runtime_scope(scope)

    # ResolveRuntimePort
    def find_candidates(self, dataset: str, identity_key: str) -> list[str]:
        return self._gateway.identity.find_candidates(dataset, identity_key)

    def add_pending(
        self,
        dataset: str,
        source_row_id: str,
        field: str,
        lookup_key: str,
        expires_at: str | None,
        payload: str | None = None,
    ) -> int:
        return self._gateway.pending.add_pending(
            dataset=dataset,
            source_row_id=source_row_id,
            field=field,
            lookup_key=lookup_key,
            expires_at=expires_at,
            payload=payload,
        )

    def list_pending_rows(self, dataset: str):
        return self._gateway.pending.list_pending_rows(dataset)

    def mark_resolved_for_source(self, source_row_id: str) -> None:
        self._gateway.pending.mark_resolved_for_source(source_row_id)

    def mark_conflict(self, pending_id: int, reason: str | None = None) -> None:
        self._gateway.pending.mark_conflict(pending_id, reason)

    def touch_attempt(self, pending_id: int) -> int:
        return self._gateway.pending.touch_attempt(pending_id)

    def sweep_expired(self, now: str, *, reason: str | None = None):
        return self._gateway.pending.sweep_expired(now, reason=reason)

    def purge_stale(
        self,
        cutoff: str,
        statuses: tuple[str, ...] | None = None,
    ) -> int:
        return self._gateway.pending.purge_stale(cutoff, statuses=statuses)

