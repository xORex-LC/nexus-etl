"""Purpose:
    Централизованная маскировка payload перед записью в report item.

Boundary:
    - Выполняет только sanitation/masking.
    - Не решает policy хранения item и не пишет в collector.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Iterable

from connector.common.sanitize import maskSecretsInObject


class PayloadSanitizer:
    """Purpose:
        Адаптер маскировки payload-объектов для отчетности.
    """

    def sanitize(self, payload_obj: Any, *, secret_fields: Iterable[str] | None = None) -> Any:
        """Purpose:
            Маскировать payload и принудительно скрыть объявленные secret-поля.

        Contract:
            - Поддерживает dict/dataclass/прочие serializable структуры.
            - Для dict дополнительно выставляет `***` по `secret_fields`.
        """
        if payload_obj is None:
            return None

        if isinstance(payload_obj, dict):
            sanitized = maskSecretsInObject(payload_obj)
        elif hasattr(payload_obj, "__dataclass_fields__"):
            sanitized = maskSecretsInObject(asdict(payload_obj))
        else:
            sanitized = maskSecretsInObject(payload_obj)

        if isinstance(sanitized, dict) and secret_fields is not None:
            for field in secret_fields:
                sanitized[str(field)] = "***"
        return sanitized
