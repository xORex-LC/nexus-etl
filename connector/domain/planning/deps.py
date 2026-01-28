from __future__ import annotations

from dataclasses import dataclass

from connector.domain.ports.cache_repository import CacheRepositoryProtocol


@dataclass
class PlanningDependencies:
    """
    Назначение:
        Объект зависимостей для планировщика конкретного датасета.

    """

    cache_repo: CacheRepositoryProtocol | None = None
