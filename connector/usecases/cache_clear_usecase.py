from __future__ import annotations

from connector.domain.ports.cache.roles import CacheAdminPort

class CacheClearUseCase:
    """
    Назначение/ответственность:
        Очистка кэша (по датасету или полностью).
    """

    def __init__(self, cache_gateway: CacheAdminPort):
        self.cache_gateway = cache_gateway

    def clear(self, dataset: str | None = None) -> dict[str, int]:
        targets = self.cache_gateway.list_datasets()
        if dataset:
            if dataset not in targets:
                raise ValueError(f"Unsupported cache dataset: {dataset}")
            targets = [dataset]

        deleted: dict[str, int] = {}
        with self.cache_gateway.transaction():
            for name in targets:
                deleted[name] = self.cache_gateway.count(name)
                self.cache_gateway.clear(name)
                self.cache_gateway.reset_meta(name)

        return deleted
