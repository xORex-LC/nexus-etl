from __future__ import annotations

from typing import Any

from connector.domain.transform.normalizer import NormalizerRule, NormalizerSpec
from connector.domain.validation.row_rules import normalize_whitespace, _boolean_parser, parse_int_strict
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow


def _normalize_text(value: Any, errors, warnings) -> str | None:
    _ = errors
    _ = warnings
    if value is None:
        return None
    normalized = normalize_whitespace(str(value))
    return normalized or None


def _organization_parser(value: Any, errors, warnings) -> int | str | None:
    _ = errors
    _ = warnings
    if value is None:
        return None
    if isinstance(value, int):
        return value
    normalized = normalize_whitespace(str(value))
    if not normalized:
        return None
    if normalized.isdigit():
        try:
            return parse_int_strict(normalized)
        except ValueError:
            return normalized
    return normalized


class EmployeesNormalizerSpec(NormalizerSpec[NormalizedEmployeesRow]):
    """
    Назначение:
        Набор правил нормализации для employees.
    """

    rules: tuple[NormalizerRule, ...] = (
        NormalizerRule("email", "email", parser=_normalize_text),
        NormalizerRule("last_name", "last_name", parser=_normalize_text),
        NormalizerRule("first_name", "first_name", parser=_normalize_text),
        NormalizerRule("middle_name", "middle_name", parser=_normalize_text),
        NormalizerRule("is_logon_disable", "is_logon_disable", parser=_boolean_parser),
        NormalizerRule("user_name", "user_name", parser=_normalize_text),
        NormalizerRule("phone", "phone", parser=_normalize_text),
        NormalizerRule("password", "password", parser=_normalize_text),
        NormalizerRule("personnel_number", "personnel_number", parser=_normalize_text),
        NormalizerRule("manager_id", "manager_id", parser=_normalize_text),
        NormalizerRule("organization_id", "organization_id", parser=_organization_parser),
        NormalizerRule("position", "position", parser=_normalize_text),
        NormalizerRule("avatar_id", "avatar_id", parser=_normalize_text),
        NormalizerRule("usr_org_tab_num", "usr_org_tab_num", parser=_normalize_text),
    )

    def build_row(self, values: dict[str, Any]) -> NormalizedEmployeesRow:
        return NormalizedEmployeesRow(
            email=values.get("email"),
            last_name=values.get("last_name"),
            first_name=values.get("first_name"),
            middle_name=values.get("middle_name"),
            is_logon_disable=values.get("is_logon_disable"),
            user_name=values.get("user_name"),
            phone=values.get("phone"),
            password=values.get("password"),
            personnel_number=values.get("personnel_number"),
            manager_id=values.get("manager_id"),
            organization_id=values.get("organization_id"),
            position=values.get("position"),
            avatar_id=values.get("avatar_id"),
            usr_org_tab_num=values.get("usr_org_tab_num"),
            resource_id=None,
        )
