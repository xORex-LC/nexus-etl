"""Payload sanitizer — маскирование report payload перед записью в items

Модуль держит единственный adapter для приведения row payload к безопасному
виду перед `AddItemEvent`. Он использует общий secret-key source из
`common/sanitize.py`, чтобы отчёты и target-safe logging не расходились по
базовому набору чувствительных ключей.

Границы ответственности:
    - Маскировать чувствительные ключи в dict/dataclass payload.
    - Форсировать declared `secret_fields` в `***` независимо от входного значения.

Вне ответственности:
    - Решение policy, сохранять ли payload в конкретный report profile.
    - Логирование или запись артефактов на диск.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from connector.common.sanitize import (
    DEFAULT_SENSITIVE_FIELD_KEYS,
    mask_secrets_in_object,
)


class PayloadSanitizer:
    """Маскировать payload-объекты отчётности единым набором чувствительных ключей."""

    def __init__(
        self, *, sensitive_keys: tuple[str, ...] = DEFAULT_SENSITIVE_FIELD_KEYS
    ) -> None:
        self._sensitive_keys = tuple(sensitive_keys)

    def sanitize(
        self, payload_obj: Any, *, secret_fields: Iterable[str] | None = None
    ) -> Any:
        """Замаскировать payload и дополнительно скрыть declared `secret_fields`.

        Args:
            payload_obj: Исходный payload любого serializable shape.
            secret_fields: Поля, которые должны быть замаскированы независимо от
                базового key-based redaction.
        """
        if payload_obj is None:
            return None

        if isinstance(payload_obj, dict):
            sanitized = mask_secrets_in_object(payload_obj, self._sensitive_keys)
        elif hasattr(payload_obj, "__dataclass_fields__"):
            sanitized = mask_secrets_in_object(
                asdict(payload_obj), self._sensitive_keys
            )
        else:
            sanitized = mask_secrets_in_object(payload_obj, self._sensitive_keys)

        if isinstance(sanitized, dict) and secret_fields is not None:
            for field in secret_fields:
                sanitized[str(field)] = "***"
        return sanitized
