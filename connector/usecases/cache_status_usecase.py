from __future__ import annotations

from connector.domain.cache_core import CacheDatasetSnapshot, CacheStatusEvaluator
from connector.domain.ports.cache.roles import CacheAdminPort


class CacheStatusUseCase:
    """
    Назначение/ответственность:
        Получение статуса кэша (counts/meta).
    """

    def __init__(
        self,
        cache_admin: CacheAdminPort,
        evaluator: CacheStatusEvaluator | None = None,
    ):
        self.cache_admin = cache_admin
        self._evaluator = evaluator or CacheStatusEvaluator()

    def status(self, dataset: str | None = None) -> dict:
        global_meta = self.cache_admin.get_meta(None).values
        snapshots = [
            CacheDatasetSnapshot(
                dataset=name,
                counts=self.cache_admin.count_by_table(name),
                meta=self.cache_admin.get_meta(name).values,
            )
            for name in self.cache_admin.list_datasets()
        ]
        return self._evaluator.evaluate(
            schema_version=global_meta.get("schema_version"),
            global_meta=global_meta,
            snapshots=snapshots,
            dataset=dataset,
        )
