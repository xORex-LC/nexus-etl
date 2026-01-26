from __future__ import annotations

from typing import Any

from connector.domain.transform.normalizer import NormalizerRule, NormalizerSpec
from connector.domain.validation.row_rules import (
    normalize_whitespace,
    _boolean_parser,
    _int_gt_zero_parser,
    _email_validator,
    _avatar_validator,
)
from connector.datasets.employees.normalized import NormalizedEmployeesRow


def _normalize_text(value: Any, errors, warnings) -> str | None:
    _ = errors
    _ = warnings
    if value is None:
        return None
    return normalize_whitespace(str(value))


class EmployeesNormalizerSpec(NormalizerSpec[NormalizedEmployeesRow]):
    """
    Назначение:
        Набор правил нормализации для employees.
    """

    rules: tuple[NormalizerRule, ...] = (
        NormalizerRule("email", "email", parser=_normalize_text, validators=(_email_validator,)),
        NormalizerRule("last_name", "last_name", parser=_normalize_text),
        NormalizerRule("first_name", "first_name", parser=_normalize_text),
        NormalizerRule("middle_name", "middle_name", parser=_normalize_text),
        NormalizerRule("is_logon_disable", "is_logon_disable", parser=_boolean_parser),
        NormalizerRule("user_name", "user_name", parser=_normalize_text),
        NormalizerRule("phone", "phone", parser=_normalize_text),
        NormalizerRule("password", "password", parser=_normalize_text),
        NormalizerRule("personnel_number", "personnel_number", parser=_normalize_text),
        NormalizerRule("manager_id", "manager_id", parser=_int_gt_zero_parser("managerId")),
        NormalizerRule("organization_id", "organization_id", parser=_int_gt_zero_parser("organization_id")),
        NormalizerRule("position", "position", parser=_normalize_text),
        NormalizerRule("avatar_id", "avatar_id", validators=(_avatar_validator,)),
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
        )
