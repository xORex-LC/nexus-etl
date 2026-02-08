from __future__ import annotations

from dataclasses import dataclass

from connector.domain.models import RowRef
from connector.domain.transform.matcher.context import MatchContext
from connector.domain.transform.matcher.match_core import MatchCore
from connector.domain.transform.matcher.match_dsl import MatchDsl
from connector.domain.transform.matcher.match_models import MatchDecisionStatus
from connector.domain.transform.matcher.rules import ResolveRules
from connector.domain.transform.dsl.loader import load_match_spec_for_dataset
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.ids.match_key import MatchKey
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow
from connector.domain.diagnostics.catalog import build_catalog

CATALOG = build_catalog("employees", strict=True)


def _employees_matching_rules():
    return MatchDsl().compile(load_match_spec_for_dataset("employees"))


@dataclass
class FakeCacheRepo:
    """
    Назначение:
        Упрощённый репозиторий для тестов matcher (только find).
    """

    responses: dict[tuple[str, str], list[dict]]

    def find(
        self,
        dataset: str,
        filters: dict[str, str],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> list[dict]:
        _ = (include_deleted, mode)
        if not filters:
            return []
        key, value = next(iter(filters.items()))
        return self.responses.get((key, value), [])


def _make_context(match_key: str, usr_org_tab_num: str | None) -> MatchContext:
    return MatchContext(
        line_no=1,
        match_key=match_key,
        match_key_complete=bool(match_key),
        usr_org_tab_num=usr_org_tab_num,
        row_ref=RowRef(line_no=1, row_id="line:1", identity_primary=None, identity_value=None),
    )


def _make_transform_result(match_context: MatchContext) -> TransformResult[NormalizedEmployeesRow]:
    row = NormalizedEmployeesRow(
        email=None,
        last_name="Doe",
        first_name="John",
        middle_name="M",
        is_logon_disable=None,
        user_name=None,
        phone=None,
        password=None,
        personnel_number="100",
        manager_id=None,
        organization_id=None,
        position=None,
        avatar_id=None,
        usr_org_tab_num=match_context.usr_org_tab_num,
        target_id=None,
    )
    return TransformResult(
        record=SourceRecord(line_no=1, record_id="rec-1", values={}),
        row=row,
        row_ref=match_context.row_ref,
        match_key=MatchKey(match_context.match_key) if match_context.match_key else None,
    )


def _make_resolve_rules() -> ResolveRules:
    return ResolveRules(build_desired_state=lambda *_: {"payload": "ok"})


def test_matcher_uses_next_identity_rule_when_primary_missing():
    matching_rules = _employees_matching_rules()
    resolve_rules = _make_resolve_rules()
    cache_repo = FakeCacheRepo(
        responses={
            ("usr_org_tab_num", "TAB-1"): [{"_id": "u-1", "usr_org_tab_num": "TAB-1"}],
        },
    )
    matcher = MatchCore(
        dataset="employees",
        cache_repo=cache_repo,
        matching_rules=matching_rules,
        resolve_rules=resolve_rules,
        include_deleted=False,
        catalog=CATALOG,
    )

    match_context = _make_context(match_key="", usr_org_tab_num="TAB-1")
    result = matcher.match(_make_transform_result(match_context))

    assert result.row is not None
    assert result.row.match_decision.status == MatchDecisionStatus.MATCHED
    assert result.row.identity.primary == "usr_org_tab_num"
    assert result.row.identity.primary_value == "TAB-1"
    assert result.row.existing == {"_id": "u-1", "usr_org_tab_num": "TAB-1"}


def test_matcher_returns_conflict_when_secondary_rule_has_multiple_candidates():
    matching_rules = _employees_matching_rules()
    resolve_rules = _make_resolve_rules()
    cache_repo = FakeCacheRepo(
        responses={
            ("usr_org_tab_num", "TAB-1"): [
                {"_id": "u-1", "usr_org_tab_num": "TAB-1"},
                {"_id": "u-2", "usr_org_tab_num": "TAB-1"},
            ],
        },
    )
    matcher = MatchCore(
        dataset="employees",
        cache_repo=cache_repo,
        matching_rules=matching_rules,
        resolve_rules=resolve_rules,
        include_deleted=False,
        catalog=CATALOG,
    )

    match_context = _make_context(match_key="", usr_org_tab_num="TAB-1")
    result = matcher.match(_make_transform_result(match_context))

    assert result.row is None
    assert result.errors
    assert result.errors[0].code == "MATCH_CONFLICT_TARGET"
    assert result.errors[0].field == "usr_org_tab_num"
