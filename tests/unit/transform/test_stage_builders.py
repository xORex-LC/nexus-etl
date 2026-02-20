from __future__ import annotations

from typing import Any

from connector.datasets.employees.spec import make_employees_spec
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.ports.transform.dictionaries import DictionaryProviderPort
from connector.domain.transform.stages.stages import (
    EnrichStage,
    MapStage,
    MatchStage,
    NormalizeStage,
    ResolveStage,
)
from connector.domain.transform.providers import TransformProviderDeps
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.cache.dsl_runtime import load_cache_dsl_runtime
from connector.infra.cache.roles import build_sqlite_cache_role_ports
from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.sqlite.engine import SqliteEngine, open_sqlite
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.identity.sqlite.schema import ensure_identity_schema


class _DummyDictionaryProvider(DictionaryProviderPort):
    def lookup(
        self,
        dict_name: str,
        key: str,
        at: Any | None = None,
        fields: tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        _ = (dict_name, key, at, fields, limit)
        return []

    def contains(self, dict_name: str, value: str, at: Any | None = None) -> bool:
        _ = (dict_name, value, at)
        return False

    def canonicalize(
        self,
        dict_name: str,
        value: str,
        at: Any | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        _ = (dict_name, value, at, limit)
        return []


def _make_engine() -> SqliteEngine:
    return open_sqlite(SqliteDbConfig(transaction_mode="deferred"), ":memory:")


def _build_gateway() -> SqliteCacheGateway:
    cache_specs = list(load_cache_dsl_runtime().cache_specs)
    cache_engine = _make_engine()
    identity_engine = _make_engine()
    ensure_identity_schema(identity_engine)
    return SqliteCacheGateway.from_engine(
        cache_engine=cache_engine,
        identity_engine=identity_engine,
        cache_specs=cache_specs,
    )


def test_employees_build_transform_stages_contract():
    spec = make_employees_spec()
    catalog = build_catalog("employees", strict=False)
    gateway = _build_gateway()
    roles = build_sqlite_cache_role_ports(gateway)
    deps = TransformProviderDeps(cache_gateway=roles.enrich_lookup, secret_store=None)

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
    gateway = _build_gateway()
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


def test_employees_build_enrich_deps_includes_dictionary_provider():
    spec = make_employees_spec()
    gateway = _build_gateway()
    roles = build_sqlite_cache_role_ports(gateway)
    dictionaries = _DummyDictionaryProvider()

    deps = spec.build_enrich_deps(
        settings=None,
        enrich_lookup=roles.enrich_lookup,
        secret_store=None,
        dictionaries=dictionaries,
    )

    assert deps.dictionaries is dictionaries
