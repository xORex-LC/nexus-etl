"""
Назначение:
    Доменный сервис детерминированного построения locator hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from connector.domain.ports.secrets.locator import SecretLocatorPort

LOCATOR_VERSION_V1 = "v1"


class SecretLocatorService(SecretLocatorPort):
    """
    Назначение:
        Канонизировать `source_ref` и формировать стабильный `locator_hash`.

    Контракт v1:
        `sha256("v1|<dataset>|<field>|<canonical_source_ref_json>")`.
    """

    def build_locator_hash(
        self,
        *,
        dataset: str,
        field: str,
        source_ref: dict[str, Any] | None,
        locator_version: str = LOCATOR_VERSION_V1,
    ) -> str:
        if locator_version != LOCATOR_VERSION_V1:
            raise ValueError(f"Unsupported locator version: {locator_version}")

        canonical_json = _canonical_source_ref_json(source_ref)
        payload = f"{locator_version}|{dataset}|{field}|{canonical_json}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def supported_versions(self) -> tuple[str, ...]:
        return (LOCATOR_VERSION_V1,)


def _canonical_source_ref_json(source_ref: dict[str, Any] | None) -> str:
    normalized = _normalize_mapping(source_ref or {})
    return json.dumps(
        normalized,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _normalize_mapping(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key in sorted(payload.keys()):
        value = _normalize_value(payload[key])
        if _is_empty(value):
            continue
        normalized[str(key)] = value
    return normalized


def _normalize_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _normalize_mapping(value)
    if isinstance(value, (list, tuple)):
        normalized_items = [_normalize_value(item) for item in value]
        return [item for item in normalized_items if not _is_empty(item)]
    return value


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if value == "":
        return True
    if isinstance(value, (list, tuple, dict)) and not value:
        return True
    return False
