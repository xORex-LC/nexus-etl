from __future__ import annotations

from typing import Any


def _to_int_or_none(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("bool is not valid for integer field")
    if isinstance(value, str):
        return int(value.strip())
    return int(value)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "y"):
            return True
        if v in ("0", "false", "no", "n"):
            return False
    raise ValueError("Invalid boolean value for isLogonDisabled")


def buildUserUpsertPayload(source: dict[str, Any]) -> dict[str, Any]:
    """
    Строит payload для PUT /user строго по контракту (14 полей).
    """
    required_keys = [
        "email",
        "last_name",
        "first_name",
        "middle_name",
        "is_logon_disable",
        "user_name",
        "phone",
        "password",
        "personnel_number",
        "organization_id",
        "position",
        "usr_org_tab_num",
    ]
    missing = [key for key in required_keys if source.get(key) in (None, "")]
    if missing:
        raise ValueError(f"Missing required fields for payload: {', '.join(missing)}")

    payload = {
        "mail": source.get("email"),
        "lastName": source.get("last_name"),
        "firstName": source.get("first_name"),
        "middleName": source.get("middle_name"),
        "isLogonDisabled": _to_bool(source.get("is_logon_disable")),
        "userName": source.get("user_name"),
        "phone": source.get("phone"),
        "password": source.get("password"),
        "personnelNumber": source.get("personnel_number"),
        "managerId": _to_int_or_none(source.get("manager_id")),
        "organization_id": _to_int_or_none(source.get("organization_id")),
        "position": source.get("position"),
        "avatarId": None,
        "usrOrgTabNum": source.get("usr_org_tab_num"),
    }
    return payload
