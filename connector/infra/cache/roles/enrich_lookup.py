from __future__ import annotations

from typing import Any

from connector.domain.ports.cache.roles import EnrichLookupPort
from connector.infra.cache.cache_gateway import SqliteCacheGateway


class SqliteEnrichLookupAdapter(EnrichLookupPort):
    """
    Role adapter lookup/exists для enrich.
    """

    def __init__(self, gateway: SqliteCacheGateway) -> None:
        self._gateway = gateway

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

