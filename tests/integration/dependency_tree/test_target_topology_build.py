"""Интеграционные тесты Stage C target topology read/build/readiness path."""

from __future__ import annotations

from pathlib import Path

import pytest

from connector.config.models import AppConfig
from connector.config.projections import to_cache_db_config, to_identity_db_config
from connector.domain.dependency_tree import (
    TargetHierarchyTopologyBuilder,
    TopologyTargetReadinessEvaluator,
)
from connector.domain.diagnostics import build_core_catalog
from connector.domain.ports.topology import TopologyFreshnessPolicy
from connector.domain.transform_dsl import load_topology_spec_for_dataset
from connector.domain.transform_dsl.compilers.topology import TopologyDsl
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.cache.roles.topology_read import SqliteTopologyCacheReadAdapter
from connector.infra.cache.dsl_runtime import load_cache_dsl_runtime
from connector.infra.identity.sqlite.schema import ensure_identity_schema
from connector.infra.sqlite.engine import open_sqlite
from connector.infra.topology import SqliteTopologyTargetReader
from connector.usecases.topology_target_build import TargetTopologyBuildUseCase

pytestmark = pytest.mark.integration


def _build_gateway(tmp_path: Path) -> SqliteCacheGateway:
    cache_engine = open_sqlite(
        to_cache_db_config(AppConfig()),
        str(tmp_path / "cache.sqlite3"),
    )
    identity_engine = open_sqlite(
        to_identity_db_config(AppConfig()),
        str(tmp_path / "identity.sqlite3"),
    )
    ensure_identity_schema(identity_engine)
    cache_specs = tuple(load_cache_dsl_runtime().cache_specs)
    return SqliteCacheGateway.from_engine(
        cache_engine=cache_engine,
        identity_engine=identity_engine,
        cache_specs=cache_specs,
    )


def _organizations_runtime():
    topology_spec = load_topology_spec_for_dataset("organizations")
    compiled = TopologyDsl().compile(topology_spec)
    cache_spec = next(
        spec
        for spec in load_cache_dsl_runtime().cache_specs
        if spec.dataset == "organizations"
    )
    return topology_spec, compiled, cache_spec


def test_sqlite_target_reader_reads_adjacency_and_metadata(
    tmp_path: Path,
    employees_registry_path,
) -> None:
    gateway = _build_gateway(tmp_path)
    topology_spec, compiled, cache_spec = _organizations_runtime()

    with gateway.transaction():
        gateway.cache.upsert(
            "organizations",
            {
                "_id": "org-100",
                "_ouid": 100,
                "code": "100",
                "name": " Head Office ",
                "match_key": "100",
                "parent_id": None,
                "updated_at": "2026-06-01T11:00:00+00:00",
            },
        )
        gateway.cache.upsert(
            "organizations",
            {
                "_id": "org-200",
                "_ouid": 200,
                "code": "200",
                "name": " FINANCE   Dept ",
                "match_key": "200",
                "parent_id": 100,
                "updated_at": "2026-06-01T11:00:00+00:00",
            },
        )
        gateway.cache.set_meta("organizations", "cache_snapshot_revision", "rev-42")
        gateway.cache.set_meta(
            "organizations",
            "last_refresh_at",
            "2026-06-01T11:30:00+00:00",
        )

    reader = SqliteTopologyTargetReader(
        cache_read=SqliteTopologyCacheReadAdapter(gateway),
        cache_spec=cache_spec,
        node_id_field=topology_spec.topology.target.node_id_field,
        parent_id_field=topology_spec.topology.target.parent_id_field,
        target_label_field=topology_spec.topology.target.target_label_field,
        payload_target_id_field=topology_spec.topology.target.payload_target_id_field,
        canonicalizer=compiled.python,
    )

    rows = tuple(reader.read_hierarchy("organizations"))
    metadata = reader.read_snapshot_metadata("organizations")
    snapshot, errors, warnings = TargetHierarchyTopologyBuilder(
        catalog=build_core_catalog(strict=True)
    ).build(rows)

    assert errors == ()
    assert warnings == ()
    assert rows[0].node_id == "100"
    assert rows[0].payload_target_id == "org-100"
    assert rows[0].label == "head office"
    assert rows[1].parent_id == "100"
    assert rows[1].payload_target_id == "org-200"
    assert rows[1].label == "finance dept"
    assert metadata.cache_snapshot_revision == "rev-42"
    assert metadata.row_count == 2
    assert snapshot.canonical_path("200") == ("head office", "finance dept")


def test_target_topology_build_usecase_returns_empty_snapshot_failure(
    tmp_path: Path,
    employees_registry_path,
) -> None:
    gateway = _build_gateway(tmp_path)
    topology_spec, compiled, cache_spec = _organizations_runtime()

    reader = SqliteTopologyTargetReader(
        cache_read=SqliteTopologyCacheReadAdapter(gateway),
        cache_spec=cache_spec,
        node_id_field=topology_spec.topology.target.node_id_field,
        parent_id_field=topology_spec.topology.target.parent_id_field,
        target_label_field=topology_spec.topology.target.target_label_field,
        payload_target_id_field=topology_spec.topology.target.payload_target_id_field,
        canonicalizer=compiled.python,
    )
    usecase = TargetTopologyBuildUseCase(
        reader=reader,
        builder=TargetHierarchyTopologyBuilder(catalog=build_core_catalog(strict=True)),
        readiness_evaluator=TopologyTargetReadinessEvaluator(
            catalog=build_core_catalog(strict=True)
        ),
    )

    result = usecase.build(
        dataset="organizations",
        freshness_policy=TopologyFreshnessPolicy(mode="none"),
        require_target_topology=True,
    )

    assert result.readiness.is_ready is False
    assert result.snapshot.nodes_by_id == {}
    assert [item.code for item in result.errors] == ["TOPOLOGY_TARGET_EMPTY"]
    assert result.warnings == ()
