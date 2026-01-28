from __future__ import annotations

from connector.domain.models import Identity, ValidationRowResult
from connector.domain.planning.rules import MatchingRules
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow


def build_identity(row: NormalizedEmployeesRow, validation: ValidationRowResult) -> Identity:
    return Identity(
        primary="match_key",
        values={
            "match_key": validation.match_key,
            "usr_org_tab_num": validation.usr_org_tab_num or "",
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
        build_identity=build_identity,
        ignored_fields=ignored_fields,
    )
