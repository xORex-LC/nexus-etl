from __future__ import annotations

from connector.domain.cache_core import CacheLifecycleEngine, CacheStatusEvaluator
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
        lifecycle_engine: CacheLifecycleEngine | None = None,
    ):
        self._engine = lifecycle_engine or CacheLifecycleEngine(
            cache_admin=cache_admin,
            status_evaluator=evaluator or CacheStatusEvaluator(),
        )

    def status(self, dataset: str | None = None) -> dict:
        return self._engine.status(dataset=dataset)
