from __future__ import annotations

from connector.domain.cache_core import CacheClearPlanner, CacheLifecycleEngine
from connector.domain.ports.cache.roles import CacheAdminPort


class CacheClearUseCase:
    """
    Назначение/ответственность:
        Очистка кэша (по датасету или полностью).
    """

    def __init__(
        self,
        cache_admin: CacheAdminPort,
        clear_planner: CacheClearPlanner | None = None,
        lifecycle_engine: CacheLifecycleEngine | None = None,
    ):
        self._engine = lifecycle_engine or CacheLifecycleEngine(
            cache_admin=cache_admin,
            clear_planner=clear_planner,
        )

    def clear(self, dataset: str | None = None) -> dict[str, int]:
        return self.clear_with_options(dataset=dataset, cascade=False)

    def clear_with_options(
        self,
        *,
        dataset: str | None = None,
        cascade: bool = False,
    ) -> dict[str, int]:
        return self._engine.clear(dataset=dataset, cascade=cascade)
