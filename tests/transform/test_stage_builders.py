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


def test_employees_build_transform_stages_contract():
    spec = make_employees_spec()
    catalog = build_catalog("employees", strict=False)
    deps = TransformProviderDeps(cache_repo=None, secret_store=None)

    map_stage, normalize_stage, enrich_stage = spec.build_transform_stages(
        enrich_deps=deps,
        catalog=catalog,
    )

    assert isinstance(map_stage, MapStage)
    assert isinstance(normalize_stage, NormalizeStage)
    assert isinstance(enrich_stage, EnrichStage)


def test_employees_build_planning_stages_contract():
    spec = make_employees_spec()
    catalog = build_catalog("employees", strict=False)
    conn = sqlite3.connect(":memory:")
    try:
        planning_deps = spec.build_planning_deps(conn, settings=None)
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

