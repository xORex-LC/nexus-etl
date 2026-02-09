from __future__ import annotations

from connector.domain.ports.cache.roles import CacheAdminPort


class CacheStatusUseCase:
    """
    Назначение/ответственность:
        Получение статуса кэша (counts/meta).
    """

    def __init__(self, cache_gateway: CacheAdminPort):
        self.cache_gateway = cache_gateway

    def status(self, dataset: str | None = None) -> dict:
        global_meta = self.cache_gateway.get_meta(None).values
        if dataset:
            counts = self.cache_gateway.count_by_table(dataset)
            return {
                "dataset": dataset,
                "schema_version": global_meta.get("schema_version"),
                "counts": counts,
                "meta": self.cache_gateway.get_meta(dataset).values,
            }

        by_dataset: dict[str, dict] = {}
        total = 0
        for name in self.cache_gateway.list_datasets():
            counts = self.cache_gateway.count_by_table(name)
            dataset_total = sum(counts.values())
            total += dataset_total
            by_dataset[name] = {
                "count": dataset_total,
                "counts": counts,
                "meta": self.cache_gateway.get_meta(name).values,
            }

        return {
            "schema_version": global_meta.get("schema_version"),
            "meta": global_meta,
            "by_dataset": by_dataset,
            "total": total,
        }
