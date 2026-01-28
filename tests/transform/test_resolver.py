from __future__ import annotations

import sqlite3

from connector.domain.models import MatchStatus, RowRef, Identity
from connector.domain.planning.deps import ResolverSettings
from connector.domain.planning.identity_keys import format_identity_key
from connector.domain.planning.match_models import MatchedRow
from connector.domain.planning.resolver import Resolver
from connector.domain.planning.rules import LinkFieldRule, LinkKeyRule, LinkRules, ResolveRules
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.identity_repository import SqliteIdentityRepository
from connector.infra.cache.pending_links_repository import SqlitePendingLinksRepository


def _make_engine() -> SqliteEngine:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    engine = SqliteEngine(conn)
    ensure_cache_ready(engine, [])
    return engine


def _make_resolver(engine: SqliteEngine, settings: ResolverSettings) -> tuple[Resolver, SqlitePendingLinksRepository]:
    identity_repo = SqliteIdentityRepository(engine)
    pending_repo = SqlitePendingLinksRepository(engine)
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
    resolver = Resolver(
        resolve_rules,
        link_rules,
        identity_repo=identity_repo,
        pending_repo=pending_repo,
        settings=settings,
    )
    return resolver, pending_repo


def _make_matched_row() -> MatchedRow:
    identity = Identity(primary="match_key", values={"match_key": "user-key"})
    row_ref = RowRef(line_no=1, row_id="line:1", identity_primary="match_key", identity_value="user-key")
    return MatchedRow(
        row_ref=row_ref,
        identity=identity,
        match_status=MatchStatus.NOT_FOUND,
        desired_state={"manager_id": "mgr", "organization_id": 10},
        existing=None,
        fingerprint="fp",
        source_links={},
        resource_id="RID-1",
    )


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
        resource_id_map={},
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
        resource_id_map={},
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
        resource_id_map={},
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
        resource_id_map={},
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
        "employees": {
            format_identity_key("match_key", "mgr"): ["99"],
        }
    }
    resolved, errors, warnings = resolver.resolve(
        matched,
        resource_id_map={},
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
        resource_id_map={},
        meta={"link_keys": {"manager_id": {"match_key": "mgr"}}},
    )

    assert errors == []
    assert warnings == []
    assert resolved is not None
    assert resolved.desired_state["manager_id"] == 42
    pending = pending_repo.list_pending_for_key("employees", format_identity_key("match_key", "mgr"))
    assert pending == []
