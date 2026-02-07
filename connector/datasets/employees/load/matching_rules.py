from __future__ import annotations

from connector.domain.models import Identity
from connector.domain.transform.matching.context import MatchContext
from connector.domain.transform.matching.rules import (
    FuzzyScoringRules,
    IdentityRule,
    MatchingRules,
    SourceDedupRules,
)
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow


def build_match_key_identity(row: NormalizedEmployeesRow, validation: MatchContext) -> Identity:
    return Identity(
        primary="match_key",
        values={
            "match_key": validation.match_key,
            "usr_org_tab_num": validation.usr_org_tab_num or "",
        },
    )


def build_usr_org_tab_num_identity(row: NormalizedEmployeesRow, validation: MatchContext) -> Identity:
    return Identity(
        primary="usr_org_tab_num",
        values={
            "usr_org_tab_num": validation.usr_org_tab_num or "",
            "match_key": validation.match_key,
        },
    )


def build_matching_rules() -> MatchingRules:
    ignored_fields = {
        "updated_at",
        "_rev",
        "deletion_date",
        "account_status",
    }
    return MatchingRules(
        build_identity=build_match_key_identity,
        ignored_fields=ignored_fields,
        identity_rules=(
            IdentityRule(name="match_key", build_identity=build_match_key_identity),
            IdentityRule(name="usr_org_tab_num", build_identity=build_usr_org_tab_num_identity),
        ),
        source_dedup=SourceDedupRules(
            enabled=True,
            on_duplicate="warn",
            on_conflict="error",
            fallback_identity_value=True,
        ),
        fuzzy=FuzzyScoringRules(
            enabled=False,
            blocking_keys=("email", "usr_org_tab_num", "personnel_number"),
            comparators={
                "email": "casefold",
                "last_name": "similarity",
                "first_name": "similarity",
                "middle_name": "similarity",
                "personnel_number": "exact",
                "usr_org_tab_num": "exact",
            },
            weights={
                "email": 3.0,
                "personnel_number": 2.0,
                "usr_org_tab_num": 2.0,
                "last_name": 1.0,
                "first_name": 1.0,
                "middle_name": 0.5,
            },
            accept_threshold=0.90,
            review_threshold=0.70,
            tie_delta=0.05,
            max_candidates=50,
            top_k=3,
            score_round=4,
        ),
    )
