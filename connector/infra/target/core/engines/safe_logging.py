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
        """Замаскировать чувствительные заголовки."""
        if headers is None:
            return None
        return self._kernel.redact_headers(headers)

    def redact_payload(self, payload: Any) -> Any:
        """Замаскировать чувствительные поля payload."""
        return self._kernel.redact_payload(payload)

    def safe_body(self, body: Any) -> Any:
        """Подготовить безопасное представление body для логов/диагностик."""
        return self._kernel.safe_body(body)

    def build_error_details(
        self,
        *,
        payload: Any,
        content_preview: str | None,
    ) -> dict[str, Any] | None:
        """Собрать безопасные детали ошибки для результирующих диагностик."""
        details: dict[str, Any] | None = None
        safe_preview = truncateText(content_preview) if content_preview else None
        if safe_preview:
            details = {"content_preview": safe_preview}
        if isinstance(payload, (dict, list)):
            details = details or {}
            safe_payload = self.safe_body(payload)
            details["response_payload"] = safe_payload
        return details

    def log_response_error(
        self,
        *,
        operation: str,
        answer_code: int | str | None,
        fault_kind: str,
        payload: Any,
        content_preview: str | None,
    ) -> None:
        """Записать warning-лог о неуспешном ответе target (ошибочный статус-код)."""
        if self._logger is None:
            return
        log_data: dict[str, Any] = {
            "operation": operation,
            "answer_code": answer_code,
            "fault_kind": fault_kind,
        }
        safe_preview = truncateText(content_preview) if content_preview else None
        if safe_preview:
            log_data["content_preview"] = safe_preview
        if isinstance(payload, (dict, list)):
            log_data["response_payload"] = self.safe_body(payload)
        elif isinstance(payload, str):
            log_data["response_payload"] = truncateText(payload)
        self._logger.warning("target request failed", **log_data)

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
        """Записать debug-лог о запланированном retry (если логгер доступен)."""
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
