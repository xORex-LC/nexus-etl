from __future__ import annotations

from typing import Any

from .validator import normalizeWhitespace


def _to_str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    return str(value)


def _to_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("bool is not valid for integer field")
    if isinstance(value, str):
        if value.strip() == "":
            return None
        return int(value.strip())
    return int(value)


def _build_match_key(last_name: str | None, first_name: str | None, middle_name: str | None, personnel_number: str | None) -> str:
    parts = [
        normalizeWhitespace(_to_str_or_none(last_name)) or "",
        normalizeWhitespace(_to_str_or_none(first_name)) or "",
        normalizeWhitespace(_to_str_or_none(middle_name)) or "",
        normalizeWhitespace(_to_str_or_none(personnel_number)) or "",
    ]
    return "|".join(parts)


def _get_first(item: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in item:
            return item[key]
    return None


def _require(value: Any, field: str) -> Any:
    """
    Проверяет, что значение не пустое/None.
    """
    if value is None:
        raise ValueError(f"Missing required field: {field}")
    if isinstance(value, str) and value.strip() == "":
        raise ValueError(f"Missing required field: {field}")
    return value


def _to_bool_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1 if value else 0
    if isinstance(value, int):
        return 1 if value != 0 else 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "y"):
            return 1
        if v in ("0", "false", "no", "n"):
            return 0
    raise ValueError("Invalid boolean value for is_logon_disabled")


def mapUserFromApi(item: dict[str, Any]) -> dict[str, Any]:
    _id = _to_str_or_none(_get_first(item, "_id", "id"))
    _ouid = _to_int_or_none(_get_first(item, "_ouid", "ouid", "userId"))
    _require(_id, "_id")
    _require(_ouid, "_ouid")

    last_name = _require(_to_str_or_none(_get_first(item, "last_name", "lastName")), "last_name")
    first_name = _require(_to_str_or_none(_get_first(item, "first_name", "firstName")), "first_name")
    middle_name = _require(_to_str_or_none(_get_first(item, "middle_name", "middleName")), "middle_name")
    personnel_number = _require(
        _to_str_or_none(_get_first(item, "personnel_number", "personnelNumber")), "personnel_number"
    )
    mail = _require(_to_str_or_none(_get_first(item, "mail", "email")), "mail")
    user_name = _require(_to_str_or_none(_get_first(item, "user_name", "userName", "username", "login")), "user_name")
    usr_org_tab_num = _require(_to_str_or_none(_get_first(item, "usr_org_tab_num", "usrOrgTabNum")), "usr_org_tab_num")
    organization_id = _require(
        _to_int_or_none(_get_first(item, "organization_id", "organizationId", "org_id", "orgId")),
        "organization_id",
    )

    match_key = _build_match_key(last_name, first_name, middle_name, personnel_number)
    if not match_key or match_key == "|||":
        raise ValueError("Cannot build match_key for user")

    return {
        "_id": _id,
        "_ouid": _ouid,
        "personnel_number": personnel_number,
        "last_name": normalizeWhitespace(last_name) or None,
        "first_name": normalizeWhitespace(first_name) or None,
        "middle_name": normalizeWhitespace(middle_name) or None,
        "match_key": match_key,
        "mail": normalizeWhitespace(mail) or mail,
        "user_name": normalizeWhitespace(user_name) or user_name,
        "phone": _to_str_or_none(_get_first(item, "phone", "mobile")),
        "usr_org_tab_num": normalizeWhitespace(usr_org_tab_num) or usr_org_tab_num,
        "organization_id": organization_id,
        "account_status": _to_str_or_none(_get_first(item, "account_status", "accountStatus")),
        "deletion_date": _to_str_or_none(_get_first(item, "deletion_date", "deletionDate")),
        "_rev": _to_str_or_none(_get_first(item, "_rev", "rev")),
        "manager_ouid": _to_int_or_none(_get_first(item, "manager_ouid", "managerId", "manager_id")),
        "is_logon_disabled": _to_bool_int(_get_first(item, "is_logon_disabled", "isLogonDisabled")),
        "position": _to_str_or_none(item.get("position")),
        "updated_at": _to_str_or_none(_get_first(item, "updated_at", "updatedAt")),
    }


def mapOrgFromApi(item: dict[str, Any]) -> dict[str, Any]:
    _ouid = _to_int_or_none(_get_first(item, "_ouid", "ouid", "id"))
    if _ouid is None:
        raise ValueError("Organization must contain _ouid")

    return {
        "_ouid": _ouid,
        "code": _to_str_or_none(item.get("code")),
        "name": _to_str_or_none(item.get("name")),
        "parent_id": _to_int_or_none(_get_first(item, "parent_id", "parentId")),
        "updated_at": _to_str_or_none(_get_first(item, "updated_at", "updatedAt")),
    }
