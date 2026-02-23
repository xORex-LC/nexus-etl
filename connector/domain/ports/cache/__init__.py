"""Порты доступа к кэшу."""

from connector.domain.ports.cache.models import CacheMeta, PendingLink, PendingRow, PendingStatus, UpsertResult
from connector.domain.ports.cache.roles import (
    ApplyRuntimePort,
    CacheRefreshPort,
    CacheAdminPort,
    EnrichLookupPort,
    MatchRuntimePort,
    PlanningRuntimePort,
    ResolveRuntimePort,
)

__all__ = [
    "ApplyRuntimePort",
    "CacheAdminPort",
    "CacheRefreshPort",
    "CacheMeta",
    "EnrichLookupPort",
    "MatchRuntimePort",
    "PlanningRuntimePort",
    "PendingLink",
    "PendingRow",
    "PendingStatus",
    "ResolveRuntimePort",
    "UpsertResult",
]
