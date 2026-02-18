"""Формирование payload для операций пользователей в Ankey REST."""

from __future__ import annotations

from typing import Any


def _to_int_or_none(value: Any) -> int | None:
    """Преобразовать значение в int или ``None`` для nullable numeric полей."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise ValueError("bool is not valid for integer field")
    if isinstance(value, str):
        return int(value.strip())
    return int(value)


def _to_bool(value: Any) -> bool:
    """Преобразовать значение в bool по правилам Ankey payload-контракта."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("1", "true", "yes", "y"):
            return True
        if normalized in ("0", "false", "no", "n"):
            return False
    raise ValueError("Invalid boolean value for isLogonDisabled")


def build_user_upsert_payload(source: dict[str, Any]) -> dict[str, Any]:
    """
    Собрать payload для alias `users.upsert` (Ankey REST).

    Контракт:
        - обязательный набор входных полей проверяется полностью;
        - `password` опционален: если не передан/пустой, поле не включается в payload;
        - выход соответствует текущему API-контракту Ankey `/ankey/managed/user/{target_id}`.
    """
    required_keys = [
        "email",
        "last_name",
        "first_name",
        "middle_name",
        "is_logon_disable",
        "user_name",
        "phone",
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
        "personnelNumber": source.get("personnel_number"),
        "managerId": _to_int_or_none(source.get("manager_id")),
        "organization_id": _to_int_or_none(source.get("organization_id")),
        "position": source.get("position"),
        "avatarId": None,
        "usrOrgTabNum": source.get("usr_org_tab_num"),
    }
    password = source.get("password")
    if password not in (None, ""):
        payload["password"] = password
    return payload


__all__ = ["build_user_upsert_payload"]
