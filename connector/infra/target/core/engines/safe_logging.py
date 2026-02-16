"""
Утилиты безопасного логирования и редактирования данных для target-слоя.
"""

from __future__ import annotations

from typing import Any

from connector.common.sanitize import truncateText
from connector.infra.target.core.kernel import TargetKernel

try:
    import structlog
except Exception:  # pragma: no cover - защитный импорт
    structlog = None  # type: ignore[assignment]


class TargetSafeLogger:
    """
    Безопасный логгер на основе structlog.

    Примечания:
        - Логирование остаётся опциональным на горячем пути.
        - Все payload/headers проходят через редактирование перед логированием.
    """

    def __init__(self, kernel: TargetKernel, *, logger_name: str = __name__) -> None:
        self._kernel = kernel
        self._logger_name = logger_name
        self._logger = structlog.get_logger(logger_name) if structlog is not None else None

    def redact_headers(self, headers: dict[str, str] | None) -> dict[str, str] | None:
        if headers is None:
            return None
        return self._kernel.redact_headers(headers)

    def redact_payload(self, payload: Any) -> Any:
        return self._kernel.redact_payload(payload)

    def safe_body(self, body: Any) -> Any:
        if isinstance(body, str):
            return truncateText(body)
        return self._kernel.safe_body(body)

    def build_error_details(
        self,
        *,
        body: Any,
        body_snippet: str | None,
    ) -> dict[str, Any] | None:
        details: dict[str, Any] | None = None
        safe_snippet = truncateText(body_snippet) if body_snippet else None
        if safe_snippet:
            details = {"body_snippet": safe_snippet}
        if isinstance(body, (dict, list)):
            details = details or {}
            details["response_json"] = self.safe_body(body)
        return details

    def debug_retry(
        self,
        *,
        operation: str,
        fault_kind: str,
        retries_used: int,
        max_retries: int,
        delay_s: float,
        mutation: str | None = None,
    ) -> None:
        if self._logger is None:
            return
        self._logger.debug(
            "запланирован повтор target-операции",
            operation=operation,
            fault_kind=fault_kind,
            retries_used=retries_used,
            max_retries=max_retries,
            delay_s=round(delay_s, 3),
            mutation=mutation,
        )
