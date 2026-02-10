from __future__ import annotations

from connector.domain.ports.cache.roles import CacheAdminPort

class CacheClearUseCase:
    """
    Назначение/ответственность:
        Очистка кэша (по датасету или полностью).
    """

    def __init__(self, cache_admin: CacheAdminPort):
        self.cache_admin = cache_admin

    def clear(self, dataset: str | None = None) -> dict[str, int]:
        targets = self.cache_admin.list_datasets()
        if dataset:
            if dataset not in targets:
                raise ValueError(f"Unsupported cache dataset: {dataset}")
            targets = [dataset]

        deleted: dict[str, int] = {}
        with self.cache_admin.transaction():
            for name in targets:
                deleted[name] = self.cache_admin.count(name)
                self.cache_admin.clear(name)
                self.cache_admin.reset_meta(name)

        return deleted
