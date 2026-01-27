from __future__ import annotations

from typing import Any

from connector.domain.validation.row_rules import normalize_whitespace
from connector.domain.transform.match_key import build_delimited_match_key
from connector.datasets.cache_sync import CacheSyncAdapterProtocol


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


def _is_deleted_flag(raw_item: dict[str, Any]) -> bool:
    status_raw = _get_first(raw_item, "accountStatus", "account_status")
    deletion_raw = _get_first(raw_item, "deletionDate", "deletion_date")
    status_norm = str(status_raw).strip().lower() if status_raw is not None else ""
    deletion_norm = str(deletion_raw).strip().lower() if deletion_raw is not None else None
    return status_norm == "deleted" or deletion_norm not in (None, "", "null")


def map_user_from_api(item: dict[str, Any]) -> dict[str, Any]:
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

    match_key = build_delimited_match_key([last_name, first_name, middle_name, personnel_number]).value
    if not match_key or match_key == "|||":
        raise ValueError("Cannot build match_key for user")

    return {
        "_id": _id,
        "_ouid": _ouid,
        "personnel_number": personnel_number,
        "last_name": normalize_whitespace(last_name) or None,
        "first_name": normalize_whitespace(first_name) or None,
        "middle_name": normalize_whitespace(middle_name) or None,
        "match_key": match_key,
        "mail": normalize_whitespace(mail) or mail,
        "user_name": normalize_whitespace(user_name) or user_name,
        "phone": _to_str_or_none(_get_first(item, "phone", "mobile")),
        "usr_org_tab_num": normalize_whitespace(usr_org_tab_num) or usr_org_tab_num,
        "organization_id": organization_id,
        "account_status": _to_str_or_none(_get_first(item, "account_status", "accountStatus")),
        "deletion_date": _to_str_or_none(_get_first(item, "deletion_date", "deletionDate")),
        "_rev": _to_str_or_none(_get_first(item, "_rev", "rev")),
        "manager_ouid": _to_int_or_none(_get_first(item, "manager_ouid", "managerId", "manager_id")),
        "is_logon_disabled": _to_bool_int(_get_first(item, "is_logon_disabled", "isLogonDisabled")),
        "position": _to_str_or_none(item.get("position")),
        "updated_at": _to_str_or_none(_get_first(item, "updated_at", "updatedAt")),
    }


class EmployeesCacheSyncAdapter(CacheSyncAdapterProtocol):
    """
    Назначение/ответственность:
        Синхронизация кэша сотрудников с целевой системой.
    """

    dataset = "employees"
    list_path = "/ankey/managed/user"
    report_entity = "user"

    def get_item_key(self, raw_item: dict[str, Any]) -> str:
        return str(_get_first(raw_item, "_id", "id") or "")

    def is_deleted(self, raw_item: dict[str, Any]) -> bool:
        return _is_deleted_flag(raw_item)

    def map_target_to_cache(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        return map_user_from_api(raw_item)
