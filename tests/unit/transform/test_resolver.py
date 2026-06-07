from __future__ import annotations

from dataclasses import dataclass

from connector.domain.dependency_tree import TopologyMatchMode
from connector.domain.models import RowRef, Identity
from connector.domain.ports.topology import (
    SourceTopologyCanonicalPath,
    TopologyLinkResolutionResult,
)
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.matcher.identity_keys import format_identity_key
from connector.domain.transform.matcher.match_models import MatchedRow, MatchDecision, MatchDecisionStatus
from connector.domain.transform.resolver.resolve_core import ResolveCore
from connector.domain.transform.resolver.pending_codec import PendingCodecAdapter
from connector.domain.transform_dsl.compilers.resolve import (
    LinkFieldRule,
    LinkKeyRule,
    LinkRules,
    ResolveRules,
    ResolveTopologyLinkPolicy,
)
from connector.domain.transform_dsl import load_sink_spec_for_dataset
from connector.domain.diagnostics.catalog import build_catalog
from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.sqlite.engine import SqliteEngine, open_sqlite
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.identity.sqlite.identity_repository import SqliteIdentityRepository
from connector.infra.identity.sqlite.pending_links_repository import SqlitePendingLinksRepository
from connector.infra.identity.sqlite.schema import ensure_identity_schema
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.cache.roles import build_sqlite_cache_role_ports


def _make_engine() -> SqliteEngine:
    engine = open_sqlite(SqliteDbConfig(transaction_mode="deferred"), ":memory:")
    ensure_cache_ready(engine, [])
    ensure_identity_schema(engine)
    return engine


def _make_resolver(engine: SqliteEngine, settings: ResolverSettings) -> tuple[ResolveCore, SqlitePendingLinksRepository]:
    catalog = build_catalog("employees", strict=True)
    pending_repo = SqlitePendingLinksRepository(engine)
    cache_gateway = SqliteCacheGateway.from_engine(cache_engine=engine, identity_engine=engine, cache_specs=[])
    cache_roles = build_sqlite_cache_role_ports(cache_gateway)
    link_rules = LinkRules(
        fields=(
            LinkFieldRule(
                field="manager_id",
                target_dataset="employees",
                resolve_keys=(LinkKeyRule(name="match_key", field="manager_id"),),
                dedup_rules=(("organization_id",),),
                target_id_field="_ouid",
                coerce="int",
            ),
        )
    )
    resolve_rules = ResolveRules(build_desired_state=lambda *_: {})
    resolver = ResolveCore(
        resolve_rules,
        link_rules,
        cache_gateway=cache_roles.planning_runtime,
        settings=settings,
        catalog=catalog,
        codec=PendingCodecAdapter(),
    )
    return resolver, pending_repo


def _make_matched_row() -> MatchedRow:
    identity = Identity(primary="match_key", values={"match_key": "user-key"})
    row_ref = RowRef(line_no=1, row_id="line:1", identity_primary="match_key", identity_value="user-key")
    return MatchedRow(
        row_ref=row_ref,
        identity=identity,
        desired_state={"manager_id": "mgr", "organization_id": 10},
        existing=None,
        fingerprint="fp",
        fingerprint_fields=("manager_id", "organization_id"),
        source_links={},
        target_id="RID-1",
        match_decision=MatchDecision(
            status=MatchDecisionStatus.NOT_FOUND,
            reason_code="identity_not_found",
        ),
    )


def _make_source_record(
    *,
    level_1: str = "Head Office",
    level_2: str = "Branch A",
    level_3: str = "Shared Team",
) -> SourceRecord:
    return SourceRecord(
        line_no=1,
        record_id="line:1",
        values={
            "Орг. единица уровня 1": level_1,
            "Орг. единица уровня 2": level_2,
            "Орг. единица уровня 3": level_3,
        },
    )


@dataclass(frozen=True)
class _FakeSourceTopologyLocatorBuilder:
    locator: SourceTopologyCanonicalPath | None

    def build(self, record: SourceRecord) -> SourceTopologyCanonicalPath | None:
        _ = record
        return self.locator


@dataclass(frozen=True)
class _FakeTopologyLinkResolutionService:
    result: TopologyLinkResolutionResult

    def resolve_link(
        self,
        *,
        field: str,
        source_locator: SourceTopologyCanonicalPath,
        target_candidate_ids: tuple[str, ...],
    ) -> TopologyLinkResolutionResult:
        _ = (field, source_locator, target_candidate_ids)
        return self.result


def test_resolver_stops_on_ambiguous_match_status():
    engine = _make_engine()
    settings = ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=5,
        pending_sweep_interval_seconds=0,
        pending_on_expire="error",
        pending_allow_partial=False,
        pending_retention_days=14,
    )
    resolver, _pending_repo = _make_resolver(engine, settings)

    matched = _make_matched_row()
    matched = MatchedRow(
        row_ref=matched.row_ref,
        identity=matched.identity,
        desired_state=matched.desired_state,
        existing=matched.existing,
        fingerprint=matched.fingerprint,
        fingerprint_fields=matched.fingerprint_fields,
        source_links=matched.source_links,
        target_id=matched.target_id,
        match_decision=MatchDecision(
            status=MatchDecisionStatus.AMBIGUOUS,
            reason_code="fuzzy_tie",
        ),
    )
    resolved, errors, warnings = resolver.resolve(
        matched,
        source_record=_make_source_record(),
        target_id_map={},
    )

    assert resolved is None
    assert warnings == []
    assert any(err.code == "RESOLVE_AMBIGUOUS" for err in errors)


def test_resolver_resolves_link_from_identity_index():
    engine = _make_engine()
    settings = ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=5,
        pending_sweep_interval_seconds=0,
        pending_on_expire="error",
        pending_allow_partial=False,
        pending_retention_days=14,
    )
    resolver, pending_repo = _make_resolver(engine, settings)
    identity_repo = SqliteIdentityRepository(engine)
    identity_repo.upsert_identity("employees", format_identity_key("match_key", "mgr"), "42")

    matched = _make_matched_row()
    resolved, errors, warnings = resolver.resolve(
        matched,
        source_record=_make_source_record(),
        target_id_map={},
        meta={"link_keys": {"manager_id": {"match_key": "mgr"}}},
    )

    assert errors == []
    assert warnings == []
    assert resolved is not None
    assert resolved.desired_state["manager_id"] == 42
    assert pending_repo.list_pending_for_key("employees", format_identity_key("match_key", "mgr")) == []


def test_resolver_creates_pending_when_no_candidate():
    engine = _make_engine()
    settings = ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=5,
        pending_sweep_interval_seconds=0,
        pending_on_expire="error",
        pending_allow_partial=False,
        pending_retention_days=14,
    )
    resolver, pending_repo = _make_resolver(engine, settings)

    matched = _make_matched_row()
    resolved, errors, warnings = resolver.resolve(
        matched,
        source_record=_make_source_record(),
        target_id_map={},
        meta={"link_keys": {"manager_id": {"match_key": "mgr"}}},
    )

    assert resolved is None
    assert errors == []
    assert any(w.code == "RESOLVE_PENDING" for w in warnings)
    pending = pending_repo.list_pending_for_key("employees", format_identity_key("match_key", "mgr"))
    assert len(pending) == 1


def test_resolver_stops_after_max_attempts():
    engine = _make_engine()
    settings = ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=1,
        pending_sweep_interval_seconds=0,
        pending_on_expire="error",
        pending_allow_partial=False,
        pending_retention_days=14,
    )
    resolver, pending_repo = _make_resolver(engine, settings)

    matched = _make_matched_row()
    resolved, errors, warnings = resolver.resolve(
        matched,
        source_record=_make_source_record(),
        target_id_map={},
        meta={"link_keys": {"manager_id": {"match_key": "mgr"}}},
    )

    assert resolved is None
    assert any(err.code == "RESOLVE_MAX_ATTEMPTS" for err in errors)
    assert warnings == []
    pending = pending_repo.list_pending_for_key("employees", format_identity_key("match_key", "mgr"))
    assert pending == []


def test_resolver_allows_partial_when_configured():
    engine = _make_engine()
    settings = ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=5,
        pending_sweep_interval_seconds=0,
        pending_on_expire="error",
        pending_allow_partial=True,
        pending_retention_days=14,
    )
    resolver, pending_repo = _make_resolver(engine, settings)

    matched = _make_matched_row()
    resolved, errors, warnings = resolver.resolve(
        matched,
        source_record=_make_source_record(),
        target_id_map={},
        meta={"link_keys": {"manager_id": {"match_key": "mgr"}}},
    )

    assert resolved is not None
    assert resolved.desired_state["manager_id"] == "mgr"
    assert errors == []
    assert any(w.code == "RESOLVE_PENDING" for w in warnings)
    pending = pending_repo.list_pending_for_key("employees", format_identity_key("match_key", "mgr"))
    assert len(pending) == 1


def test_resolver_uses_batch_index_for_candidates():
    engine = _make_engine()
    settings = ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=5,
        pending_sweep_interval_seconds=0,
        pending_on_expire="error",
        pending_allow_partial=False,
        pending_retention_days=14,
    )
    resolver, pending_repo = _make_resolver(engine, settings)

    matched = _make_matched_row()
    batch_index = {
        format_identity_key("match_key", "mgr"): ["99"],
    }
    resolved, errors, warnings = resolver.resolve(
        matched,
        source_record=_make_source_record(),
        target_id_map={},
        meta={"link_keys": {"manager_id": {"match_key": "mgr"}}},
        batch_index=batch_index,
    )

    assert errors == []
    assert warnings == []
    assert resolved is not None
    assert resolved.desired_state["manager_id"] == 99
    pending = pending_repo.list_pending_for_key("employees", format_identity_key("match_key", "mgr"))
    assert pending == []


def test_resolver_dedup_rules_narrow_candidates():
    engine = _make_engine()
    settings = ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=5,
        pending_sweep_interval_seconds=0,
        pending_on_expire="error",
        pending_allow_partial=False,
        pending_retention_days=14,
    )
    resolver, pending_repo = _make_resolver(engine, settings)
    identity_repo = SqliteIdentityRepository(engine)
    identity_repo.upsert_identity("employees", format_identity_key("match_key", "mgr"), "42")
    identity_repo.upsert_identity("employees", format_identity_key("match_key", "mgr"), "43")
    identity_repo.upsert_identity("employees", format_identity_key("organization_id", "10"), "42")

    matched = _make_matched_row()
    resolved, errors, warnings = resolver.resolve(
        matched,
        source_record=_make_source_record(),
        target_id_map={},
        meta={"link_keys": {"manager_id": {"match_key": "mgr"}}},
    )

    assert errors == []
    assert warnings == []
    assert resolved is not None
    assert resolved.desired_state["manager_id"] == 42
    pending = pending_repo.list_pending_for_key("employees", format_identity_key("match_key", "mgr"))
    assert pending == []


def test_resolver_hard_error_on_unresolved_rule():
    engine = _make_engine()
    settings = ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=5,
        pending_sweep_interval_seconds=0,
        pending_on_expire="error",
        pending_allow_partial=True,
        pending_retention_days=14,
    )
    catalog = build_catalog("employees", strict=True)
    pending_repo = SqlitePendingLinksRepository(engine)
    cache_gateway = SqliteCacheGateway.from_engine(cache_engine=engine, identity_engine=engine, cache_specs=[])
    cache_roles = build_sqlite_cache_role_ports(cache_gateway)
    resolver = ResolveCore(
        ResolveRules(build_desired_state=lambda *_: {}),
        LinkRules(
            fields=(
                LinkFieldRule(
                    field="manager_id",
                    target_dataset="employees",
                    resolve_keys=(LinkKeyRule(name="match_key", field="manager_id"),),
                    on_unresolved="hard_error",
                ),
            )
        ),
        cache_gateway=cache_roles.planning_runtime,
        settings=settings,
        catalog=catalog,
        codec=PendingCodecAdapter(),
    )

    matched = _make_matched_row()
    resolved, errors, warnings = resolver.resolve(
        matched,
        source_record=_make_source_record(),
        target_id_map={},
        meta={"link_keys": {"manager_id": {"match_key": "mgr"}}},
    )

    assert resolved is None
    assert warnings == []
    assert any(err.code == "RESOLVE_CONFLICT" for err in errors)
    assert pending_repo.list_pending_for_key("employees", format_identity_key("match_key", "mgr")) == []


def test_resolver_validates_sink_for_resolved_mutations():
    engine = _make_engine()
    settings = ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=5,
        pending_sweep_interval_seconds=0,
        pending_on_expire="error",
        pending_allow_partial=False,
        pending_retention_days=14,
    )
    catalog = build_catalog("employees", strict=True)
    identity_repo = SqliteIdentityRepository(engine)
    cache_gateway = SqliteCacheGateway.from_engine(cache_engine=engine, identity_engine=engine, cache_specs=[])
    cache_roles = build_sqlite_cache_role_ports(cache_gateway)
    # manager_id in sink schema is int; here we intentionally produce non-int resolved value.
    identity_repo.upsert_identity("employees", format_identity_key("match_key", "mgr"), "bad-int")

    resolver = ResolveCore(
        ResolveRules(build_desired_state=lambda *_: {}),
        LinkRules(
            fields=(
                LinkFieldRule(
                    field="manager_id",
                    target_dataset="employees",
                    resolve_keys=(LinkKeyRule(name="match_key", field="manager_id"),),
                    target_id_field="_ouid",
                    coerce="int",
                ),
            )
        ),
        cache_gateway=cache_roles.planning_runtime,
        settings=settings,
        catalog=catalog,
        sink_spec=load_sink_spec_for_dataset("employees"),
        codec=PendingCodecAdapter(),
    )

    matched = _make_matched_row()
    resolved, errors, warnings = resolver.resolve(
        matched,
        source_record=_make_source_record(),
        target_id_map={},
        meta={"link_keys": {"manager_id": {"match_key": "mgr"}}},
    )

    assert resolved is None
    assert warnings == []
    assert any(err.code == "SINK_TYPE_INVALID" and err.field == "manager_id" for err in errors)


def test_resolver_uses_topology_to_disambiguate_link_candidates():
    engine = _make_engine()
    settings = ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=5,
        pending_sweep_interval_seconds=0,
        pending_on_expire="error",
        pending_allow_partial=False,
        pending_retention_days=14,
    )
    catalog = build_catalog("employees", strict=True)
    identity_repo = SqliteIdentityRepository(engine)
    cache_gateway = SqliteCacheGateway.from_engine(
        cache_engine=engine,
        identity_engine=engine,
        cache_specs=[],
    )
    cache_roles = build_sqlite_cache_role_ports(cache_gateway)
    with engine.transaction():
        identity_repo.upsert_identity(
            "organizations",
            format_identity_key("name", "Shared Team"),
            "100",
        )
        identity_repo.upsert_identity(
            "organizations",
            format_identity_key("name", "Shared Team"),
            "200",
        )

    resolver = ResolveCore(
        ResolveRules(build_desired_state=lambda *_: {}),
        LinkRules(
            fields=(
                LinkFieldRule(
                    field="organization_id",
                    target_dataset="organizations",
                    resolve_keys=(LinkKeyRule(name="name", field="organization_id"),),
                    target_id_field="_ouid",
                    coerce="int",
                    on_unresolved="hard_error",
                ),
            )
        ),
        cache_gateway=cache_roles.planning_runtime,
        settings=settings,
        catalog=catalog,
        codec=PendingCodecAdapter(),
        topology_link_policy=ResolveTopologyLinkPolicy(
            enabled=True,
            field="organization_id",
            on_missing_topology="hard_error",
            on_ambiguous_topology="hard_error",
        ),
        topology_link_service=_FakeTopologyLinkResolutionService(
            result=TopologyLinkResolutionResult(
                resolved_field="organization_id",
                resolved_target_id=200,
                is_pending=False,
                is_ambiguous=False,
                mode=TopologyMatchMode.EXACT_CANONICAL_PATH,
                reason="resolved_by_exact_canonical_path",
                evidence={},
            )
        ),
        source_topology_locator_builder=_FakeSourceTopologyLocatorBuilder(
            locator=SourceTopologyCanonicalPath(
                canonical_segments=("head office", "branch a", "shared team")
            )
        ),
    )

    matched = _make_matched_row()
    matched = MatchedRow(
        row_ref=matched.row_ref,
        identity=matched.identity,
        desired_state={"organization_id": "Shared Team"},
        existing=matched.existing,
        fingerprint=matched.fingerprint,
        fingerprint_fields=("organization_id",),
        source_links=matched.source_links,
        target_id=matched.target_id,
        match_decision=matched.match_decision,
    )
    resolved, errors, warnings = resolver.resolve(
        matched,
        source_record=_make_source_record(),
        target_id_map={},
    )

    assert errors == []
    assert warnings == []
    assert resolved is not None
    assert resolved.desired_state["organization_id"] == 200


def test_resolver_creates_pending_when_topology_is_ambiguous_and_policy_allows_pending():
    engine = _make_engine()
    settings = ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=5,
        pending_sweep_interval_seconds=0,
        pending_on_expire="error",
        pending_allow_partial=False,
        pending_retention_days=14,
    )
    catalog = build_catalog("employees", strict=True)
    pending_repo = SqlitePendingLinksRepository(engine)
    identity_repo = SqliteIdentityRepository(engine)
    cache_gateway = SqliteCacheGateway.from_engine(
        cache_engine=engine,
        identity_engine=engine,
        cache_specs=[],
    )
    cache_roles = build_sqlite_cache_role_ports(cache_gateway)
    with engine.transaction():
        identity_repo.upsert_identity(
            "organizations",
            format_identity_key("name", "Shared Team"),
            "100",
        )
        identity_repo.upsert_identity(
            "organizations",
            format_identity_key("name", "Shared Team"),
            "200",
        )

    resolver = ResolveCore(
        ResolveRules(build_desired_state=lambda *_: {}),
        LinkRules(
            fields=(
                LinkFieldRule(
                    field="organization_id",
                    target_dataset="organizations",
                    resolve_keys=(LinkKeyRule(name="name", field="organization_id"),),
                    on_unresolved="hard_error",
                ),
            )
        ),
        cache_gateway=cache_roles.planning_runtime,
        settings=settings,
        catalog=catalog,
        codec=PendingCodecAdapter(),
        topology_link_policy=ResolveTopologyLinkPolicy(
            enabled=True,
            field="organization_id",
            on_missing_topology="pending",
            on_ambiguous_topology="pending",
        ),
        topology_link_service=_FakeTopologyLinkResolutionService(
            result=TopologyLinkResolutionResult(
                resolved_field="organization_id",
                resolved_target_id=None,
                is_pending=False,
                is_ambiguous=True,
                mode=TopologyMatchMode.AMBIGUOUS,
                reason="ambiguous_on_exact_leaf_parent_chain",
                evidence={},
            )
        ),
        source_topology_locator_builder=_FakeSourceTopologyLocatorBuilder(
            locator=SourceTopologyCanonicalPath(
                canonical_segments=("head office", "branch a", "shared team")
            )
        ),
    )

    matched = _make_matched_row()
    matched = MatchedRow(
        row_ref=matched.row_ref,
        identity=matched.identity,
        desired_state={"organization_id": "Shared Team"},
        existing=matched.existing,
        fingerprint=matched.fingerprint,
        fingerprint_fields=("organization_id",),
        source_links=matched.source_links,
        target_id=matched.target_id,
        match_decision=matched.match_decision,
    )
    resolved, errors, warnings = resolver.resolve(
        matched,
        source_record=_make_source_record(),
        target_id_map={},
    )

    assert resolved is None
    assert errors == []
    assert any(item.code == "RESOLVE_PENDING" for item in warnings)
    pending = pending_repo.list_pending_for_key("organizations", format_identity_key("name", "Shared Team"))
    assert len(pending) == 1


def test_resolver_hard_errors_when_topology_source_locator_is_missing():
    engine = _make_engine()
    settings = ResolverSettings(
        pending_ttl_seconds=120,
        pending_max_attempts=5,
        pending_sweep_interval_seconds=0,
        pending_on_expire="error",
        pending_allow_partial=False,
        pending_retention_days=14,
    )
    catalog = build_catalog("employees", strict=True)
    identity_repo = SqliteIdentityRepository(engine)
    cache_gateway = SqliteCacheGateway.from_engine(
        cache_engine=engine,
        identity_engine=engine,
        cache_specs=[],
    )
    cache_roles = build_sqlite_cache_role_ports(cache_gateway)
    with engine.transaction():
        identity_repo.upsert_identity(
            "organizations",
            format_identity_key("name", "Shared Team"),
            "100",
        )
        identity_repo.upsert_identity(
            "organizations",
            format_identity_key("name", "Shared Team"),
            "200",
        )

    resolver = ResolveCore(
        ResolveRules(build_desired_state=lambda *_: {}),
        LinkRules(
            fields=(
                LinkFieldRule(
                    field="organization_id",
                    target_dataset="organizations",
                    resolve_keys=(LinkKeyRule(name="name", field="organization_id"),),
                    on_unresolved="hard_error",
                ),
            )
        ),
        cache_gateway=cache_roles.planning_runtime,
        settings=settings,
        catalog=catalog,
        codec=PendingCodecAdapter(),
        topology_link_policy=ResolveTopologyLinkPolicy(
            enabled=True,
            field="organization_id",
            on_missing_topology="hard_error",
            on_ambiguous_topology="hard_error",
        ),
        source_topology_locator_builder=_FakeSourceTopologyLocatorBuilder(locator=None),
    )

    matched = _make_matched_row()
    matched = MatchedRow(
        row_ref=matched.row_ref,
        identity=matched.identity,
        desired_state={"organization_id": "Shared Team"},
        existing=matched.existing,
        fingerprint=matched.fingerprint,
        fingerprint_fields=("organization_id",),
        source_links=matched.source_links,
        target_id=matched.target_id,
        match_decision=matched.match_decision,
    )
    resolved, errors, warnings = resolver.resolve(
        matched,
        source_record=_make_source_record(level_1="", level_2="", level_3=""),
        target_id_map={},
    )

    assert resolved is None
    assert warnings == []
    assert any(item.code == "RESOLVE_CONFLICT" for item in errors)
