from __future__ import annotations

from connector.domain.ports.cache_repository import CacheRepositoryProtocol


class CacheStatusUseCase:
    """
    Назначение/ответственность:
        Получение статуса кэша (counts/meta).
    """

    def __init__(self, cache_repo: CacheRepositoryProtocol):
        self.cache_repo = cache_repo

    def status(self, dataset: str | None = None) -> dict:
        meta = self.cache_repo.get_meta(None).values
        if dataset:
            counts = self.cache_repo.count_by_table(dataset)
            return {
                "dataset": dataset,
                "schema_version": meta.get("schema_version"),
                "counts": counts,
                "meta": self.cache_repo.get_meta(dataset).values,
            }

        users_count = self.cache_repo.count("employees")
        org_count = self.cache_repo.count("organizations")
        return {
            "schema_version": meta.get("schema_version"),
            "users_count": users_count,
            "org_count": org_count,
            "users_last_refresh_at": meta.get("users_last_refresh_at"),
            "org_last_refresh_at": meta.get("org_last_refresh_at"),
            "source_api_base": meta.get("source_api_base"),
            "meta_users_count": _safe_int(meta.get("users_count")),
            "meta_org_count": _safe_int(meta.get("org_count")),
        }


def _safe_int(value: str | None) -> int:
    if value is None or value == "":
        return 0
    try:
        return int(value)
    except ValueError:
        return 0
