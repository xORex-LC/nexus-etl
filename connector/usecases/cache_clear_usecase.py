from __future__ import annotations

from connector.domain.ports.cache_repository import CacheRepositoryProtocol
from connector.datasets.cache_sync import CacheSyncAdapterProtocol


class CacheClearUseCase:
    """
    Назначение/ответственность:
        Очистка кэша (по датасету или полностью).
    """

    def __init__(self, cache_repo: CacheRepositoryProtocol, adapters: list[CacheSyncAdapterProtocol]):
        self.cache_repo = cache_repo
        self.adapters = adapters

    def clear(self, dataset: str | None = None) -> dict[str, int]:
        targets = self.adapters
        if dataset:
            targets = [a for a in self.adapters if a.dataset == dataset]
            if not targets:
                raise ValueError(f"Unsupported cache dataset: {dataset}")

        deleted_users = deleted_orgs = 0
        with self.cache_repo.transaction():
            for adapter in targets:
                if adapter.dataset == "employees":
                    deleted_users = self.cache_repo.count("employees")
                if adapter.dataset == "organizations":
                    deleted_orgs = self.cache_repo.count("organizations")
                self.cache_repo.clear(adapter.dataset)

            self.cache_repo.set_meta(None, "users_count", "0")
            self.cache_repo.set_meta(None, "org_count", "0")
            self.cache_repo.set_meta(None, "users_last_refresh_at", None)
            self.cache_repo.set_meta(None, "org_last_refresh_at", None)
            self.cache_repo.set_meta(None, "source_api_base", None)

        return {"users_deleted": deleted_users, "orgs_deleted": deleted_orgs}
