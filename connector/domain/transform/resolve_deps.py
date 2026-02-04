from __future__ import annotations

from dataclasses import dataclass

from connector.domain.ports.cache_repository import CacheRepositoryProtocol
from connector.domain.ports.identity_repository import IdentityRepository
from connector.domain.ports.pending_links_repository import PendingLinksRepository


@dataclass(frozen=True)
class ResolverSettings:
    """
    Назначение:
        Настройки поведения resolver/pending механики.
    """

    pending_ttl_seconds: int
    pending_max_attempts: int
    pending_sweep_interval_seconds: int
    pending_on_expire: str
    pending_allow_partial: bool
    pending_retention_days: int


@dataclass
class PlanningDependencies:
    """
    Назначение:
        Объект зависимостей для планировщика конкретного датасета.

    """

    cache_repo: CacheRepositoryProtocol | None = None
    identity_repo: IdentityRepository | None = None
    pending_repo: PendingLinksRepository | None = None
    resolver_settings: ResolverSettings | None = None
