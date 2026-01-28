from __future__ import annotations

from typing import Any

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


def map_org_from_api(item: dict[str, Any]) -> dict[str, Any]:
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


class OrganizationsCacheSyncAdapter(CacheSyncAdapterProtocol):
    """
    Назначение/ответственность:
        Синхронизация кэша организаций с целевой системой.
    """

    dataset = "organizations"
    list_path = "/ankey/managed/organization"
    report_entity = "org"

    def get_item_key(self, raw_item: dict[str, Any]) -> str:
        return str(_get_first(raw_item, "_ouid", "ouid", "id") or "")

    def is_deleted(self, raw_item: dict[str, Any]) -> bool:
        return False

    def map_target_to_cache(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        return map_org_from_api(raw_item)
