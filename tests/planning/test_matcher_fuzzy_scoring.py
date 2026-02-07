from __future__ import annotations

from dataclasses import dataclass

from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.models import Identity, MatchStatus, RowRef
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.ids.match_key import MatchKey
from connector.domain.transform.matching.deduplication_transform import DeduplicationTransform
from connector.domain.transform.matching.match_models import MatchDecisionReason
from connector.domain.transform.matching.rules import FuzzyScoringRules, MatchingRules, ResolveRules
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
        return self.responses.get((key, str(value)), [])


def _row(*, email: str, first_name: str = "John") -> NormalizedEmployeesRow:
    return NormalizedEmployeesRow(
        email=email,
        last_name="Doe",
        first_name=first_name,
        middle_name="M",
        is_logon_disable=False,
        user_name="jdoe",
        phone=None,
        password=None,
        personnel_number="100",
        manager_id=None,
        organization_id=1,
        position="Engineer",
        avatar_id=None,
        usr_org_tab_num="TAB-100",
        target_id=None,
    )


def _result(row: NormalizedEmployeesRow) -> TransformResult[NormalizedEmployeesRow]:
    return TransformResult(
        record=SourceRecord(line_no=1, record_id="rec-1", values={}),
        row=row,
        row_ref=RowRef(line_no=1, row_id="row-1", identity_primary=None, identity_value=None),
        match_key=MatchKey("mk:missing"),
    )


def _resolve_rules() -> ResolveRules:
    return ResolveRules(
        build_desired_state=lambda row, _: {
            "email": row.email,
            "first_name": row.first_name,
            "last_name": row.last_name,
            "match_key": "mk:missing",
        }
    )


def _matcher(
    *,
    responses: dict[tuple[str, str], list[dict]],
    fuzzy: FuzzyScoringRules,
) -> DeduplicationTransform:
    return DeduplicationTransform(
        dataset="employees",
        cache_repo=FakeCacheRepo(responses=responses),
        matching_rules=MatchingRules(
            build_identity=lambda _row, _ctx: Identity(
                primary="match_key",
                values={"match_key": "mk:missing"},
            ),
            fuzzy=fuzzy,
        ),
        resolve_rules=_resolve_rules(),
        include_deleted=False,
        catalog=CATALOG,
    )


def test_fuzzy_accept_returns_matched():
    matcher = _matcher(
        responses={
            ("email", "john@example.com"): [
                {"_id": "u-1", "email": "john@example.com", "first_name": "john"},
            ],
        },
        fuzzy=FuzzyScoringRules(
            enabled=True,
            blocking_keys=("email",),
            comparators={"email": "casefold", "first_name": "similarity"},
            weights={"email": 3.0, "first_name": 1.0},
            accept_threshold=0.90,
            review_threshold=0.70,
        ),
    )

    result = matcher.match(_result(_row(email="john@example.com", first_name="John")))

    assert result.row is not None
    assert result.row.match_status == MatchStatus.MATCHED
    assert result.row.match_mode == "fuzzy"
    assert result.row.decision_reason == MatchDecisionReason.FUZZY_ACCEPT
    assert result.row.score is not None and result.row.score >= 0.90
    assert result.row.existing is not None


def test_fuzzy_review_returns_conflict_target():
    matcher = _matcher(
        responses={
            ("email", "john@example.com"): [
                {"_id": "u-2", "email": "john@example.com", "first_name": "Joan"},
            ],
        },
        fuzzy=FuzzyScoringRules(
            enabled=True,
            blocking_keys=("email",),
            comparators={"first_name": "similarity"},
            weights={"first_name": 1.0},
            accept_threshold=0.90,
            review_threshold=0.70,
        ),
    )

    result = matcher.match(_result(_row(email="john@example.com", first_name="John")))

    assert result.row is not None
    assert result.row.match_status == MatchStatus.CONFLICT_TARGET
    assert result.row.decision_reason == MatchDecisionReason.FUZZY_REVIEW
    assert result.row.existing is None


def test_fuzzy_reject_returns_not_found():
    matcher = _matcher(
        responses={
            ("email", "john@example.com"): [
                {"_id": "u-3", "email": "john@example.com", "first_name": "ZZZZ"},
            ],
        },
        fuzzy=FuzzyScoringRules(
            enabled=True,
            blocking_keys=("email",),
            comparators={"first_name": "similarity"},
            weights={"first_name": 1.0},
            accept_threshold=0.95,
            review_threshold=0.70,
        ),
    )

    result = matcher.match(_result(_row(email="john@example.com", first_name="John")))

    assert result.row is not None
    assert result.row.match_status == MatchStatus.NOT_FOUND
    assert result.row.decision_reason == MatchDecisionReason.FUZZY_REJECT
    assert result.row.existing is None


def test_fuzzy_tie_returns_conflict_target():
    matcher = _matcher(
        responses={
            ("email", "john@example.com"): [
                {"_id": "u-4", "email": "john@example.com", "first_name": "ZZZ"},
                {"_id": "u-5", "email": "john@example.com", "first_name": "YYY"},
            ],
        },
        fuzzy=FuzzyScoringRules(
            enabled=True,
            blocking_keys=("email",),
            comparators={"first_name": "exact"},
            weights={"first_name": 1.0},
            accept_threshold=0.90,
            review_threshold=0.10,
            tie_delta=0.01,
        ),
    )

    result = matcher.match(_result(_row(email="john@example.com", first_name="John")))

    assert result.row is not None
    assert result.row.match_status == MatchStatus.CONFLICT_TARGET
    assert result.row.decision_reason == MatchDecisionReason.FUZZY_TIE
    assert result.row.existing is None


def test_top_candidates_default_is_three():
    matcher = _matcher(
        responses={
            ("email", "john@example.com"): [
                {"_id": "u-10", "email": "john@example.com", "first_name": "John"},
                {"_id": "u-11", "email": "john@example.com", "first_name": "Johan"},
                {"_id": "u-12", "email": "john@example.com", "first_name": "Joan"},
                {"_id": "u-13", "email": "john@example.com", "first_name": "Jon"},
            ],
        },
        fuzzy=FuzzyScoringRules(
            enabled=True,
            blocking_keys=("email",),
            comparators={"first_name": "similarity"},
            weights={"first_name": 1.0},
            accept_threshold=0.99,
            review_threshold=0.10,
            # top_k not set -> default 3
        ),
    )

    result = matcher.match(_result(_row(email="john@example.com", first_name="John")))

    assert result.row is not None
    assert len(result.row.top_candidates) == 3


def test_fuzzy_respects_max_candidates_limit():
    matcher = _matcher(
        responses={
            ("email", "john@example.com"): [
                {"_id": "u-20", "email": "john@example.com", "first_name": "ZZZZ"},
            ],
            ("usr_org_tab_num", "TAB-100"): [
                {"_id": "u-21", "email": "other@example.com", "first_name": "John"},
            ],
        },
        fuzzy=FuzzyScoringRules(
            enabled=True,
            blocking_keys=("email", "usr_org_tab_num"),
            comparators={"first_name": "exact"},
            weights={"first_name": 1.0},
            accept_threshold=0.90,
            review_threshold=0.70,
            max_candidates=1,
        ),
    )

    result = matcher.match(_result(_row(email="john@example.com", first_name="John")))

    assert result.row is not None
    assert result.row.match_status == MatchStatus.NOT_FOUND
    assert result.row.decision_reason == MatchDecisionReason.FUZZY_REJECT
    assert len(result.row.top_candidates) == 1


def test_unknown_comparator_falls_back_to_exact():
    matcher = _matcher(
        responses={
            ("email", "john@example.com"): [
                {"_id": "u-22", "email": "john@example.com", "first_name": "John"},
            ],
        },
        fuzzy=FuzzyScoringRules(
            enabled=True,
            blocking_keys=("email",),
            comparators={"first_name": "unsupported_mode"},
            weights={"first_name": 1.0},
            accept_threshold=0.90,
            review_threshold=0.70,
        ),
    )

    result = matcher.match(_result(_row(email="john@example.com", first_name="John")))

    assert result.row is not None
    assert result.row.match_status == MatchStatus.MATCHED
    assert result.row.decision_reason == MatchDecisionReason.FUZZY_ACCEPT
    assert result.row.score == 1.0


def test_fuzzy_disabled_keeps_legacy_identity_not_found_path():
    matcher = _matcher(
        responses={
            ("email", "john@example.com"): [
                {"_id": "u-23", "email": "john@example.com", "first_name": "John"},
            ],
        },
        fuzzy=FuzzyScoringRules(
            enabled=False,
            blocking_keys=("email",),
            comparators={"first_name": "similarity"},
            weights={"first_name": 1.0},
            accept_threshold=0.90,
            review_threshold=0.70,
        ),
    )

    result = matcher.match(_result(_row(email="john@example.com", first_name="John")))

    assert result.row is not None
    assert result.row.match_mode == "exact"
    assert result.row.match_status == MatchStatus.NOT_FOUND
    assert result.row.decision_reason == MatchDecisionReason.IDENTITY_NOT_FOUND
    assert result.row.top_candidates == ()
