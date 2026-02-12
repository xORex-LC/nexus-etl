from __future__ import annotations

from connector.domain.ports.cache.roles import ApplyRuntimePort
from connector.infra.cache.cache_gateway import SqliteCacheGateway


class SqliteApplyRuntimeAdapter(ApplyRuntimePort):
    """
    Role adapter post-apply синхронизации identity/pending.
    """

    def __init__(self, gateway: SqliteCacheGateway) -> None:
        self._gateway = gateway

    def upsert_identity(self, dataset: str, identity_key: str, resolved_id: str) -> None:
        self._gateway.identity.upsert_identity(dataset, identity_key, resolved_id)

    def list_pending_for_key(self, dataset: str, lookup_key: str):
        return self._gateway.pending.list_pending_for_key(dataset, lookup_key)

    def mark_resolved(self, pending_id: int) -> None:
        self._gateway.pending.mark_resolved(pending_id)

