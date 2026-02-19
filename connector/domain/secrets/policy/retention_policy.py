"""Назначение:
    Чистая retention policy для lifecycle секретов после apply-операции.

Граница ответственности:
    Модуль нормализует декларативный `secret_lifecycle` в runtime-политику.
    Он не удаляет секреты и не взаимодействует с storage.
"""

from __future__ import annotations

from typing import Any

LIFECYCLE_MODE_PERSISTENT = "persistent"
LIFECYCLE_MODE_EPHEMERAL = "ephemeral"
DEFAULT_LOCATOR_VERSION = "v1"


def normalize_secret_lifecycle(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Назначение:
        Привести сырой lifecycle-пейлоад к стабильному policy-контракту.

    Контракт:
        - `mode`: `persistent` по умолчанию, допустимы только `persistent|ephemeral`.
        - `delete_on_success`:
          - если явно задан bool, используется как есть;
          - иначе для `ephemeral` становится `True`, для `persistent` — `False`.
        - `ttl_seconds`: только положительный int, иначе `None`.
    """
    mode = LIFECYCLE_MODE_PERSISTENT
    delete_on_success = False
    ttl_seconds: int | None = None
    explicit_delete: bool | None = None

    if isinstance(raw, dict):
        raw_mode = raw.get("mode")
        if isinstance(raw_mode, str) and raw_mode in {LIFECYCLE_MODE_PERSISTENT, LIFECYCLE_MODE_EPHEMERAL}:
            mode = raw_mode
        raw_delete = raw.get("delete_on_success")
        if isinstance(raw_delete, bool):
            explicit_delete = raw_delete
        raw_ttl = raw.get("ttl_seconds")
        if isinstance(raw_ttl, int) and raw_ttl > 0:
            ttl_seconds = raw_ttl

    if explicit_delete is not None:
        delete_on_success = explicit_delete
    elif mode == LIFECYCLE_MODE_EPHEMERAL:
        delete_on_success = True

    return {
        "mode": mode,
        "delete_on_success": delete_on_success,
        "ttl_seconds": ttl_seconds,
    }


__all__ = [
    "DEFAULT_LOCATOR_VERSION",
    "LIFECYCLE_MODE_EPHEMERAL",
    "LIFECYCLE_MODE_PERSISTENT",
    "normalize_secret_lifecycle",
]
