from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .cacheSourceApi import mapOrgFromApi, mapUserFromApi

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

def loadUsersFromJson(path: str, errors: list[tuple[str, Exception]] | None = None) -> list[dict[str, Any]]:
    """
    Парсит JSON пользователей и нормализует поля под таблицу users.
    """
    items = _read_json_list(path)
    result: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("User item must be an object")

        key = _to_str_or_none(item.get("_id")) or f"idx:{idx}"
        try:
            normalized = mapUserFromApi(item)
            result.append(normalized)
        except Exception as exc:  # noqa: BLE001
            if errors is not None:
                errors.append((key, exc))
                continue
            raise
    return result

def loadOrganizationsFromJson(path: str, errors: list[tuple[str, Exception]] | None = None) -> list[dict[str, Any]]:
    """
    Парсит JSON организаций и нормализует поля под таблицу organizations.
    """
    items = _read_json_list(path)
    result: list[dict[str, Any]] = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            raise ValueError("Organization item must be an object")
        key = _to_str_or_none(item.get("_ouid")) or f"idx:{idx}"
        try:
            normalized = mapOrgFromApi(item)
            result.append(normalized)
        except Exception as exc:  # noqa: BLE001
            if errors is not None:
                errors.append((key, exc))
                continue
            raise
    return result
