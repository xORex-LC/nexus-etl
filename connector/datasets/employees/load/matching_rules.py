from __future__ import annotations

from connector.domain.models import Identity, ValidationRowResult
from connector.domain.planning.rules import MatchingRules
from connector.domain.validation.row_rules import normalize_whitespace
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow


def build_identity(row: NormalizedEmployeesRow, validation: ValidationRowResult) -> Identity:
    return Identity(
        primary="match_key",
        values={
            "match_key": validation.match_key,
            "usr_org_tab_num": validation.usr_org_tab_num or "",
        },
    )


def build_links(row: NormalizedEmployeesRow, _: ValidationRowResult) -> dict[str, Identity]:
    links: dict[str, Identity] = {}
    manager_id = row.manager_id
    if manager_id is None or isinstance(manager_id, int):
        return links
    match_key_value = normalize_whitespace(str(manager_id))
    if match_key_value:
        links["manager"] = Identity(primary="match_key", values={"match_key": match_key_value})
    return links


def build_matching_rules() -> MatchingRules:
    ignored_fields = {
        "updated_at",
        "_rev",
        "deletion_date",
        "account_status",
    }
    return MatchingRules(
        build_identity=build_identity,
        build_links=build_links,
        ignored_fields=ignored_fields,
    )
