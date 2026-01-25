from __future__ import annotations

from connector.domain.validation.row_rules import (
    FieldRule,
    _avatar_validator,
    _boolean_parser,
    _email_validator,
    _int_gt_zero_parser,
)

FIELD_RULES: tuple[FieldRule, ...] = (
    # TODO: TECHDEBT - re-evaluate required fields after enrich is in place.
    FieldRule("email", 0, validators=(_email_validator,)),
    FieldRule("lastName", 1),
    FieldRule("firstName", 2),
    FieldRule("middleName", 3),
    FieldRule("isLogonDisable", 4, parser=_boolean_parser),
    FieldRule("userName", 5),
    FieldRule("phone", 6),
    FieldRule("password", 7),
    FieldRule("personnelNumber", 8),
    FieldRule("managerId", 9, parser=_int_gt_zero_parser("managerId")),
    FieldRule("organization_id", 10, parser=_int_gt_zero_parser("organization_id")),
    FieldRule("position", 11),
    FieldRule("avatarId", 12, validators=(_avatar_validator,)),
    FieldRule("usrOrgTabNum", 13),
)
