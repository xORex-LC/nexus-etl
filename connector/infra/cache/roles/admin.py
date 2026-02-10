from __future__ import annotations

from connector.domain.ports.cache.roles import CacheAdminPort
from connector.infra.cache.cache_gateway import SqliteCacheGateway


class SqliteCacheAdminAdapter(CacheAdminPort):
    """
    Role adapter для административного API кэша.
    """

    def __init__(self, gateway: SqliteCacheGateway) -> None:
        self._gateway = gateway

    def transaction(self):
        return self._gateway.transaction()

    def upsert(self, dataset: str, write_model: dict):
        return self._gateway.cache.upsert(dataset, write_model)

    def count(self, dataset: str) -> int:
        return self._gateway.cache.count(dataset)

    def count_by_table(self, dataset: str) -> dict[str, int]:
        return self._gateway.cache.count_by_table(dataset)

    def clear(self, dataset: str) -> None:
        self._gateway.cache.clear(dataset)

    def rebuild(self, dataset: str) -> None:
        self._gateway.cache.rebuild(dataset)

    def list_datasets(self) -> list[str]:
        return self._gateway.cache.list_datasets()

    def get_meta(self, dataset: str | None = None):
        return self._gateway.cache.get_meta(dataset)

    def set_meta(self, dataset: str | None, key: str, value: str | None) -> None:
        self._gateway.cache.set_meta(dataset, key, value)

    def reset_meta(self, dataset: str) -> None:
        self._gateway.cache.reset_meta(dataset)
