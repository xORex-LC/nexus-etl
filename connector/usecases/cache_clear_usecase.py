from __future__ import annotations

from connector.domain.ports.cache_repository import CacheRepositoryProtocol

class CacheClearUseCase:
    """
    Назначение/ответственность:
        Очистка кэша (по датасету или полностью).
    """

    def __init__(self, cache_repo: CacheRepositoryProtocol):
        self.cache_repo = cache_repo

    def clear(self, dataset: str | None = None) -> dict[str, int]:
        targets = self.cache_repo.list_datasets()
        if dataset:
            if dataset not in targets:
                raise ValueError(f"Unsupported cache dataset: {dataset}")
            targets = [dataset]

        deleted: dict[str, int] = {}
        with self.cache_repo.transaction():
            for name in targets:
                deleted[name] = self.cache_repo.count(name)
                self.cache_repo.clear(name)
                self.cache_repo.reset_meta(name)

        return deleted
