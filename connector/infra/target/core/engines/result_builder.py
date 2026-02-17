"""
TargetResultBuilder — конструктор ExecutionResult для gateway.
"""

from __future__ import annotations

from typing import Any

from connector.common.sanitize import truncateText
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.target.execution import ExecutionResult
from connector.infra.target.core.engines.error_normalizer import NormalizedFault
from connector.infra.target.core.engines.fault_handler import TargetFaultHandler
from connector.infra.target.core.engines.safe_logging import TargetSafeLogger
from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.driver import DriverError, DriverResponse


class TargetResultBuilder:
    """
    Конструктор ExecutionResult для gateway.

    Инкапсулирует все варианты создания ExecutionResult:
    успешный ответ, ошибки из DriverError/DriverResponse,
    неожиданные сбои и spec-ошибки конфигурации.
    """

    def __init__(self, kernel: TargetKernel, safe_logger: TargetSafeLogger) -> None:
        """Инициализировать builder на зависимостях kernel и safe_logger."""
        self._kernel = kernel
        self._safe_logger = safe_logger

    def execute_success(self, resp: DriverResponse) -> ExecutionResult:
        """Построить успешный ``ExecutionResult`` из ``DriverResponse``."""
        safe_payload = self._safe_logger.safe_body(resp.payload)
        return ExecutionResult(
            ok=True,
            answer_code=resp.answer_code,
            response_payload=safe_payload,
            response_format=resp.payload_format,
        )

    def from_driver_error(
        self,
        exc: DriverError,
        normalized: NormalizedFault,
        error_details: dict[str, Any] | None,
    ) -> ExecutionResult:
        """Построить ``ExecutionResult`` по ``DriverError``."""
        return ExecutionResult(
            ok=False,
            answer_code=exc.answer_code,
            error_code=normalized.error_code,
            error_message=truncateText(str(exc)),
            error_reason=exc.error_reason,
            error_details=error_details,
        )

    def from_response_error(
        self,
        resp: DriverResponse,
        normalized: NormalizedFault,
        error_details: dict[str, Any] | None,
    ) -> ExecutionResult:
        """Построить ``ExecutionResult`` по неуспешному ``DriverResponse``."""
        safe_payload = error_details.get("response_payload") if isinstance(error_details, dict) else None
        return ExecutionResult(
            ok=False,
            answer_code=resp.answer_code,
            response_payload=safe_payload,
            response_format=resp.payload_format if safe_payload is not None else "none",
            error_code=normalized.error_code,
            error_message=TargetFaultHandler.format_answer_failure(resp.answer_code),
            error_reason=resp.error_reason,
            error_details=error_details,
        )

    def unexpected_failure(self, exc: Exception) -> ExecutionResult:
        """Построить ``ExecutionResult`` для неожидаемого исключения."""
        return ExecutionResult(
            ok=False,
            error_code=SystemErrorCode.INFRA_UNAVAILABLE,
            error_message=truncateText(str(exc)),
        )

    def spec_error(self, message: str) -> ExecutionResult:
        """Построить ``ExecutionResult`` для ошибки конфигурации/spec."""
        return ExecutionResult(
            ok=False,
            error_code=self._kernel.system_error_code("SPEC"),
            error_message=truncateText(message),
        )
