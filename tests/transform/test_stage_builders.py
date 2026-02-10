from __future__ import annotations

import sqlite3

from connector.datasets.employees.spec import make_employees_spec
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.transform.stages.stages import (
    EnrichStage,
    MapStage,
    MatchStage,
    NormalizeStage,
    ResolveStage,
)
from connector.domain.transform.providers import TransformProviderDeps
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.cache.repository.identity_repository import SqliteIdentityRepository
from connector.infra.cache.repository.pending_links_repository import SqlitePendingLinksRepository
from connector.infra.cache.repository.cache_repository import SqliteCacheRepository
from connector.infra.cache.roles import build_sqlite_cache_role_ports
from connector.infra.cache.backends.sqlite.engine import SqliteEngine


def test_employees_build_transform_stages_contract():
    spec = make_employees_spec()
    catalog = build_catalog("employees", strict=False)
    conn = sqlite3.connect(":memory:")
    try:
        gateway = _build_gateway(conn=conn, spec=spec)
        roles = build_sqlite_cache_role_ports(gateway)
        deps = TransformProviderDeps(cache_gateway=roles.enrich_lookup, secret_store=None)

        map_stage, normalize_stage, enrich_stage = spec.build_transform_stages(
            enrich_deps=deps,
            catalog=catalog,
        )

        assert isinstance(map_stage, MapStage)
        assert isinstance(normalize_stage, NormalizeStage)
        assert isinstance(enrich_stage, EnrichStage)
    finally:
        conn.close()


def test_employees_build_planning_stages_contract():
    spec = make_employees_spec()
    catalog = build_catalog("employees", strict=False)
    conn = sqlite3.connect(":memory:")
    try:
        gateway = _build_gateway(conn=conn, spec=spec)
        roles = build_sqlite_cache_role_ports(gateway)
        planning_deps = spec.build_planning_deps(settings=None, planning_runtime=roles.planning_runtime)
        match_stage, resolve_stage = spec.build_planning_stages(
            planning_deps=planning_deps,
            catalog=catalog,
            include_deleted=False,
            settings=None,
        )
        assert isinstance(match_stage, MatchStage)
        assert isinstance(resolve_stage, ResolveStage)
    finally:
        conn.close()


def _build_gateway(*, conn, spec) -> SqliteCacheGateway:
    engine = SqliteEngine(conn)
    cache_repo = SqliteCacheRepository(engine, spec.build_cache_specs())
    identity_repo = SqliteIdentityRepository(engine)
    pending_repo = SqlitePendingLinksRepository(engine)
    return SqliteCacheGateway(
        engine=engine,
        cache_repo=cache_repo,
        identity_repo=identity_repo,
        pending_repo=pending_repo,
    )
