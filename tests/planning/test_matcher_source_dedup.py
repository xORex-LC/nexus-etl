from __future__ import annotations

from dataclasses import dataclass

from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.models import Identity, RowRef
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.ids.match_key import MatchKey
from connector.domain.transform.matcher.match_core import MatchCore
from connector.domain.transform.matcher.match_models import MatchDecisionStatus
from connector.domain.transform.matcher.rules import (
    IdentityRule,
    MatchingRules,
    ResolveRules,
    SourceDedupRules,
)
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow


CATALOG = build_catalog("employees", strict=True)


@dataclass
class FakeCacheRepo:
    responses: dict[tuple[str, str], list[dict]]

    def find(
        self,
        dataset: str,
        filters: dict[str, str],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> list[dict]:
        _ = (dataset, include_deleted, mode)
        if not filters:
            return []
        key, value = next(iter(filters.items()))
        return self.responses.get((key, value), [])


@dataclass
class FakeIdentityRepo:
    values: dict[tuple[str, str, str], str]

    def upsert_identity(self, dataset: str, identity_key: str, resolved_id: str) -> None:
        _ = (dataset, identity_key, resolved_id)

    def find_candidates(self, dataset: str, identity_key: str) -> list[str]:
        _ = (dataset, identity_key)
        return []

    def set_runtime_state(self, scope: str, dataset: str, state_key: str, state_value: str) -> None:
        self.values[(scope, dataset, state_key)] = state_value

    def get_runtime_state(self, scope: str, dataset: str, state_key: str) -> str | None:
        return self.values.get((scope, dataset, state_key))

    def clear_runtime_scope(self, scope: str) -> None:
        for key in [k for k in self.values if k[0] == scope]:
            del self.values[key]


def _row(*, phone: str, position: str = "Engineer") -> NormalizedEmployeesRow:
    return NormalizedEmployeesRow(
        email="john@example.com",
        last_name="Doe",
        first_name="John",
        middle_name="M",
        is_logon_disable=False,
        user_name="jdoe",
        phone=phone,
        password=None,
        personnel_number="100",
        manager_id=None,
        organization_id=1,
        position=position,
        avatar_id=None,
        usr_org_tab_num="TAB-100",
        target_id=None,
    )


def _result(row: NormalizedEmployeesRow) -> TransformResult[NormalizedEmployeesRow]:
    return TransformResult(
        record=SourceRecord(line_no=1, record_id="rec-1", values={}),
        row=row,
        row_ref=RowRef(line_no=1, row_id="row-1", identity_primary=None, identity_value=None),
        match_key=MatchKey("Doe|John|M|100"),
    )


def _resolve_rules() -> ResolveRules:
    return ResolveRules(
        build_desired_state=lambda row, _: {
            "match_key": "Doe|John|M|100",
            "phone": row.phone,
        }
    )


def _build_matcher(*, on_conflict: str = "error") -> MatchCore:
    matching_rules = MatchingRules(
        identity_rules=(
            IdentityRule(
                name="match_key",
                build_identity=lambda _row, _ctx: Identity(
                    primary="match_key",
                    values={"match_key": "Doe|John|M|100"},
                ),
            ),
        ),
        source_dedup=SourceDedupRules(
            enabled=True,
            on_duplicate="warn",
            on_conflict=on_conflict,
        ),
    )
    cache_repo = FakeCacheRepo(
        responses={
            ("match_key", "Doe|John|M|100"): [{"_id": "u-1", "match_key": "Doe|John|M|100"}],
        }
    )
    return MatchCore(
        dataset="employees",
        cache_repo=cache_repo,
        matching_rules=matching_rules,
        resolve_rules=_resolve_rules(),
        include_deleted=False,
        catalog=CATALOG,
    )


def test_source_dedup_duplicate_is_hard_dropped_with_warning():
    matcher = _build_matcher()

    first = matcher.match_with_source_dedup(_result(_row(phone="+111")))
    second = matcher.match_with_source_dedup(_result(_row(phone="+111")))

    assert first.row is not None
    assert first.row.match_decision.status == MatchDecisionStatus.MATCHED

    assert second.row is None
    assert second.errors == ()
    assert any(w.code == "MATCH_DUPLICATE_SOURCE" for w in second.warnings)
    assert second.meta.get("match_drop_reason") == "duplicate_source"


def test_source_dedup_conflict_is_hard_dropped_with_error():
    matcher = _build_matcher(on_conflict="error")

    first = matcher.match_with_source_dedup(_result(_row(phone="+111")))
    second = matcher.match_with_source_dedup(_result(_row(phone="+222")))

    assert first.row is not None
    assert second.row is None
    assert any(e.code == "MATCH_CONFLICT_SOURCE" for e in second.errors)
    assert second.meta.get("match_drop_reason") == "conflict_source"


def test_source_dedup_requires_canonical_identity_key():
    matching_rules = MatchingRules(
        identity_rules=(
            IdentityRule(
                name="empty",
                build_identity=lambda _row, _ctx: Identity(primary="", values={"": "same"}),
            ),
        ),
        source_dedup=SourceDedupRules(
            enabled=True,
            on_duplicate="warn",
            on_conflict="error",
        ),
    )
    cache_repo = FakeCacheRepo(responses={("", "same"): [{"_id": "u-1"}]})
    matcher = MatchCore(
        dataset="employees",
        cache_repo=cache_repo,
        matching_rules=matching_rules,
        resolve_rules=_resolve_rules(),
        include_deleted=False,
        catalog=CATALOG,
    )

    first = matcher.match_with_source_dedup(_result(_row(phone="+111")))
    second = matcher.match_with_source_dedup(_result(_row(phone="+111")))

    assert first.row is not None
    assert second.row is not None
    assert second.errors == ()
    assert second.warnings == ()


def test_source_dedup_reads_scoped_runtime_state_from_identity_repo():
    state_repo = FakeIdentityRepo(values={})
    matcher1 = _build_matcher()
    matcher1.identity_repo = state_repo
    matcher1.bind_runtime_scope("run:scope")
    first = matcher1.match_with_source_dedup(_result(_row(phone="+111")))
    assert first.row is not None

    matcher2 = _build_matcher()
    matcher2.identity_repo = state_repo
    matcher2.bind_runtime_scope("run:scope")
    second = matcher2.match_with_source_dedup(_result(_row(phone="+111")))

    assert second.row is None
    assert any(w.code == "MATCH_DUPLICATE_SOURCE" for w in second.warnings)


def test_source_dedup_uses_canonical_key_with_identity_primary():
    matching_rules = MatchingRules(
        identity_rules=(
            IdentityRule(
                name="variable_primary",
                build_identity=lambda row, _ctx: Identity(
                    primary="phone" if row.position == "Engineer" else "personnel_number",
                    values={
                        "phone": "same-key",
                        "personnel_number": "same-key",
                    },
                ),
            ),
        ),
        source_dedup=SourceDedupRules(
            enabled=True,
            on_duplicate="warn",
            on_conflict="error",
        ),
    )
    cache_repo = FakeCacheRepo(
        responses={
            ("phone", "same-key"): [{"_id": "u-1"}],
            ("personnel_number", "same-key"): [{"_id": "u-2"}],
        }
    )
    matcher = MatchCore(
        dataset="employees",
        cache_repo=cache_repo,
        matching_rules=matching_rules,
        resolve_rules=_resolve_rules(),
        include_deleted=False,
        catalog=CATALOG,
    )

    first = matcher.match_with_source_dedup(_result(_row(phone="+111", position="Engineer")))
    second = matcher.match_with_source_dedup(_result(_row(phone="+111", position="Manager")))

    assert first.row is not None
    assert second.row is not None
    assert second.errors == ()
    assert second.warnings == ()
