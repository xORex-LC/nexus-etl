from __future__ import annotations

from connector.domain.models import Identity, ValidationRowResult
from connector.domain.planning.rules import IdentityRule, MatchingRules
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow


def build_match_key_identity(row: NormalizedEmployeesRow, validation: ValidationRowResult) -> Identity:
    return Identity(
        primary="match_key",
        values={
            "match_key": validation.match_key,
            "usr_org_tab_num": validation.usr_org_tab_num or "",
        },
    )


def build_usr_org_tab_num_identity(row: NormalizedEmployeesRow, validation: ValidationRowResult) -> Identity:
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
    )
