from __future__ import annotations

from dataclasses import dataclass

from connector.domain.ports.cache.roles import (
    ApplyRuntimePort,
    CacheAdminPort,
    CacheRefreshPort,
    EnrichLookupPort,
    PlanningRuntimePort,
)
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.cache.roles.admin import SqliteCacheAdminAdapter
from connector.infra.cache.roles.apply_runtime import SqliteApplyRuntimeAdapter
from connector.infra.cache.roles.cache_refresh import SqliteCacheRefreshAdapter
from connector.infra.cache.roles.enrich_lookup import SqliteEnrichLookupAdapter
from connector.infra.cache.roles.planning_runtime import SqlitePlanningRuntimeAdapter


@dataclass(frozen=True)
class SqliteCacheRolePorts:
    """
    Единый набор role-based портов поверх namespaced gateway.
    """

    cache_admin: CacheAdminPort
    cache_refresh: CacheRefreshPort
    enrich_lookup: EnrichLookupPort
    planning_runtime: PlanningRuntimePort
    apply_runtime: ApplyRuntimePort


def build_sqlite_cache_role_ports(gateway: SqliteCacheGateway) -> SqliteCacheRolePorts:
    """
    Собрать role-based порты поверх SqliteCacheGateway.
    """
    cache_admin = SqliteCacheAdminAdapter(gateway)
    apply_runtime = SqliteApplyRuntimeAdapter(gateway)
    enrich_lookup = SqliteEnrichLookupAdapter(gateway)
    planning_runtime = SqlitePlanningRuntimeAdapter(gateway)
    cache_refresh = SqliteCacheRefreshAdapter(cache_admin, apply_runtime)

    return SqliteCacheRolePorts(
        cache_admin=cache_admin,
        cache_refresh=cache_refresh,
        enrich_lookup=enrich_lookup,
        planning_runtime=planning_runtime,
        apply_runtime=apply_runtime,
    )

