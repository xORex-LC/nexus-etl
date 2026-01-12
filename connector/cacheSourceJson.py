from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .validator import normalizeWhitespace

def _read_json_list(path: str) -> list[Any]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, list):
        return raw
    if isinstance(raw, dict):
        for key in ("items", "data", "users", "organizations", "orgs"):
            value = raw.get(key)
            if isinstance(value, list):
                return value
    raise ValueError("Unsupported JSON structure for cache source")

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

def loadUsersFromJson(path: str) -> list[dict[str, Any]]:
    """
    Парсит JSON пользователей и нормализует поля под таблицу users.
    """
    items = _read_json_list(path)
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("User item must be an object")

        _id = _to_str_or_none(_get_first(item, "_id", "id"))
        _ouid = _to_int_or_none(_get_first(item, "_ouid", "ouid", "userId"))
        if _id is None or _ouid is None:
            raise ValueError("User must contain _id and _ouid")

        last_name = _to_str_or_none(_get_first(item, "last_name", "lastName"))
        first_name = _to_str_or_none(_get_first(item, "first_name", "firstName"))
        middle_name = _to_str_or_none(_get_first(item, "middle_name", "middleName"))
        personnel_number = _to_str_or_none(_get_first(item, "personnel_number", "personnelNumber"))
        match_key = _build_match_key(last_name, first_name, middle_name, personnel_number)

        normalized = {
            "_id": _id,
            "_ouid": _ouid,
            "personnel_number": personnel_number,
            "last_name": normalizeWhitespace(last_name) or None,
            "first_name": normalizeWhitespace(first_name) or None,
            "middle_name": normalizeWhitespace(middle_name) or None,
            "match_key": match_key,
            "mail": _to_str_or_none(_get_first(item, "mail", "email")),
            "user_name": _to_str_or_none(_get_first(item, "user_name", "userName", "username", "login")),
            "phone": _to_str_or_none(item.get("phone")),
            "updated_at": _to_str_or_none(_get_first(item, "updated_at", "updatedAt")),
        }

        result.append(normalized)
    return result

def loadOrganizationsFromJson(path: str) -> list[dict[str, Any]]:
    """
    Парсит JSON организаций и нормализует поля под таблицу organizations.
    """
    items = _read_json_list(path)
    result: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Organization item must be an object")

        _ouid = _to_int_or_none(_get_first(item, "_ouid", "ouid", "id"))
        if _ouid is None:
            raise ValueError("Organization must contain _ouid")

        normalized = {
            "_ouid": _ouid,
            "code": _to_str_or_none(item.get("code")),
            "name": _to_str_or_none(item.get("name")),
            "parent_id": _to_int_or_none(_get_first(item, "parent_id", "parentId")),
            "updated_at": _to_str_or_none(_get_first(item, "updated_at", "updatedAt")),
        }

        result.append(normalized)
    return result