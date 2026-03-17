"""
TargetFaultHandler — классификация ошибок и формирование error_details для gateway.
"""

from __future__ import annotations

from typing import Any

from connector.common.sanitize import truncate_text
from connector.infra.target.core.engines.error_normalizer import (
    NormalizedFault,
    TargetErrorNormalizer,
)
from connector.infra.target.core.engines.safe_logging import TargetSafeLogger
from connector.infra.target.core.kernel import ResolvedRetryAction, TargetKernel
from connector.infra.target.driver import DriverError, DriverResponse


class TargetFaultHandler:
    """
    Классификация ошибок и формирование error_details для gateway.

    Инкапсулирует логику перевода DriverError/DriverResponse в
    (NormalizedFault, ResolvedRetryAction), а также сборку error_details
    с учётом redaction и эскалации.
    """

    def __init__(
        self,
        kernel: TargetKernel,
        normalizer: TargetErrorNormalizer,
        safe_logger: TargetSafeLogger,
    ) -> None:
        """Инициализировать обработчик ошибок на базе kernel/normalizer/logger."""
        self._kernel = kernel
        self._normalizer = normalizer
        self._safe_logger = safe_logger

    def from_driver_error(
        self,
        exc: DriverError,
    ) -> tuple[NormalizedFault, ResolvedRetryAction]:
        """Классифицировать ``DriverError`` и вычислить retry-решение."""
        status_code = self.as_status_code(exc.answer_code)
        normalized = self._normalizer.from_status_or_code(
            status_code=status_code,
            error_code=exc.code,
        )
        retry_action = self._kernel.resolve_retry_action(
            fault_kind=normalized.fault_kind,
            status_code=status_code,
            error_reason=exc.error_reason,
        )
        return normalized, retry_action

    def from_driver_response(
        self,
        resp: DriverResponse,
    ) -> tuple[NormalizedFault, ResolvedRetryAction]:
        """Классифицировать неуспешный ``DriverResponse`` и вычислить retry-решение."""
        status_code = self.as_status_code(resp.answer_code)
        normalized = self._normalizer.from_status(status_code)
        retry_action = self._kernel.resolve_retry_action(
            fault_kind=normalized.fault_kind,
            status_code=status_code,
            error_reason=resp.error_reason,
        )
        return normalized, retry_action

    def build_exc_details(
        self,
        exc: DriverError,
        retry_action: ResolvedRetryAction,
    ) -> dict[str, Any] | None:
        """Собрать ``error_details`` из ``DriverError`` с redaction и эскалацией."""
        error_details: dict[str, Any] | None = None
        if isinstance(exc.details, dict) and exc.details:
            safe_details = self._safe_logger.safe_body(exc.details)
            error_details = safe_details if isinstance(safe_details, dict) else None
        content_preview = exc.content_preview or (
            error_details.get("content_preview")
            if isinstance(error_details, dict)
            else None
        )
        if content_preview is not None:
            error_details = dict(error_details or {})
            error_details["content_preview"] = truncate_text(str(content_preview))
        if exc.error_reason is not None:
            error_details = dict(error_details or {})
            error_details["error_reason"] = exc.error_reason
        if retry_action.directive == "ESCALATE":
            error_details = self.mark_escalated(error_details)
        return error_details

    def build_resp_details(
        self,
        resp: DriverResponse,
        retry_action: ResolvedRetryAction,
    ) -> dict[str, Any] | None:
        """Собрать ``error_details`` из неуспешного ``DriverResponse``."""
        details = self._safe_logger.build_error_details(
            payload=resp.payload,
            content_preview=resp.content_preview,
        )
        if resp.error_reason is not None:
            details = dict(details or {})
            details["error_reason"] = resp.error_reason
        if retry_action.directive == "ESCALATE":
            details = self.mark_escalated(details)
        return details

    @staticmethod
    def as_status_code(answer_code: int | str | None) -> int | None:
        """Извлечь числовой статус из ``answer_code`` (если применимо)."""
        if type(answer_code) is int:
            return answer_code
        return None

    @staticmethod
    def mark_escalated(details: dict[str, Any] | None) -> dict[str, Any]:
        """Добавить признак эскалации в ``error_details``."""
        payload = dict(details or {})
        payload["escalated"] = True
        return payload

    @staticmethod
    def format_answer_failure(answer_code: int | str | None) -> str:
        """Сформировать человекочитаемое сообщение ошибки по ``answer_code``."""
        if answer_code is None:
            return "target operation failed"
        return f"target answer {answer_code}"
