from __future__ import annotations

from connector.domain.ports.cache.models import CacheMeta
from connector.domain.ports.cache.roles import TopologyCacheReadPort
from connector.infra.cache.cache_gateway import SqliteCacheGateway


class SqliteTopologyCacheReadAdapter(TopologyCacheReadPort):
    """
    Role adapter: read-only доступ к кэшу для topology bootstrap.

    Изолирует конкретный SqliteCacheGateway внутри infra/cache/, чтобы
    topology read seam зависел только от TopologyCacheReadPort.
    """

    def __init__(self, gateway: SqliteCacheGateway) -> None:
        self._gateway = gateway

    def read_all(self, dataset: str, *, include_deleted: bool = False) -> list[dict]:
        return self._gateway.cache.read_all(dataset, include_deleted=include_deleted)

    def get_meta(self, dataset: str | None = None) -> CacheMeta:
        return self._gateway.cache.get_meta(dataset)

    def count(self, dataset: str) -> int:
        return self._gateway.cache.count(dataset)
