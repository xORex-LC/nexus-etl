from __future__ import annotations

from typing import Any

from .validation.row_rules import normalize_whitespace as normalizeWhitespace

def _normalize_str(value: str | None) -> str | None:
    return normalizeWhitespace(value)

def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
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
    return None

def build_user_diff(existing: dict[str, Any] | None, desired: dict[str, Any]) -> dict[str, Any]:
    """
    Строит diff между кэшем и желаемым состоянием (CSV).
    Поля соответствуют PUT-модели; пароль не раскрывается.
    """
    diff: dict[str, Any] = {}

    def _compare(cache_value: Any, desired_value: Any, key: str) -> None:
        if cache_value != desired_value:
            diff[key] = {"from": cache_value, "to": desired_value}

    cache_mail = _normalize_str(existing.get("mail")) if existing else None
    desired_mail = _normalize_str(desired.get("email"))
    _compare(cache_mail, desired_mail, "mail")

    cache_ln = _normalize_str(existing.get("last_name")) if existing else None
    cache_fn = _normalize_str(existing.get("first_name")) if existing else None
    cache_mn = _normalize_str(existing.get("middle_name")) if existing else None
    desired_ln = _normalize_str(desired.get("last_name"))
    desired_fn = _normalize_str(desired.get("first_name"))
    desired_mn = _normalize_str(desired.get("middle_name"))
    _compare(cache_ln, desired_ln, "last_name")
    _compare(cache_fn, desired_fn, "first_name")
    _compare(cache_mn, desired_mn, "middle_name")

    cache_is_disabled = _to_bool(existing.get("is_logon_disabled")) if existing else None
    desired_is_disabled = desired.get("is_logon_disable")
    _compare(cache_is_disabled, desired_is_disabled, "is_logon_disable")

    cache_username = _normalize_str(existing.get("user_name")) if existing else None
    desired_username = _normalize_str(desired.get("user_name"))
    _compare(cache_username, desired_username, "user_name")

    cache_phone = _normalize_str(existing.get("phone")) if existing else None
    desired_phone = _normalize_str(desired.get("phone"))
    _compare(cache_phone, desired_phone, "phone")

    cache_pn = existing.get("personnel_number") if existing else None
    desired_pn = desired.get("personnel_number")
    _compare(cache_pn, desired_pn, "personnel_number")

    cache_mgr = existing.get("manager_ouid") if existing else None
    desired_mgr = desired.get("manager_id")
    _compare(cache_mgr, desired_mgr, "manager_id")

    cache_org = existing.get("organization_id") if existing else None
    desired_org = desired.get("organization_id")
    _compare(cache_org, desired_org, "organization_id")

    cache_position = _normalize_str(existing.get("position")) if existing else None
    desired_position = _normalize_str(desired.get("position"))
    _compare(cache_position, desired_position, "position")

    cache_usr_org_tab = _normalize_str(existing.get("usr_org_tab_num")) if existing else None
    desired_usr_org_tab = _normalize_str(desired.get("usr_org_tab_num"))
    _compare(cache_usr_org_tab, desired_usr_org_tab, "usr_org_tab_num")

    if desired.get("password"):
        diff["password"] = {"will_change": True}

    return diff