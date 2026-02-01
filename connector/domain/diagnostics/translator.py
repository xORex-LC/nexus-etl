from __future__ import annotations

from typing import Any

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.system_codes import SystemErrorCode
from connector.domain.diagnostics.policies import map_system_code
from connector.domain.models import DiagnosticItem, DiagnosticStage
from connector.domain.diagnostics.factory import DiagnosticFactory
from connector.domain.ports.execution import ExecutionResult


class Translator:
    """
    Назначение:
        Единственная точка преобразования внешних ошибок в DiagnosticItem.
    """

    def __init__(self, catalog: ErrorCatalog) -> None:
        self.catalog = catalog
        self.factory = DiagnosticFactory(catalog)

    def from_exception(self, stage: DiagnosticStage, exc: Exception) -> DiagnosticItem:
        """
        Назначение:
            Преобразовать исключение в DiagnosticItem.
        """
        return self.factory.error(
            stage=stage,
            code="INTERNAL_ERROR",
            field=None,
            message=str(exc),
            record_ref=None,
            details=None,
        )

    def from_http(self, stage: DiagnosticStage, status: int | None, body: Any | None) -> DiagnosticItem:
        """
        Назначение:
            Преобразовать HTTP-ответ в DiagnosticItem.
        """
        code = "SINK_HTTP_ERROR"
        message = f"HTTP {status}" if status is not None else "HTTP error"
        details = {"status": status, "body": body} if status is not None or body is not None else None
        return self.factory.error(
            stage=stage,
            code=code,
            field=None,
            message=message,
            record_ref=None,
            details=details,
        )

    def from_execution_result(self, stage: DiagnosticStage, result: ExecutionResult) -> DiagnosticItem:
        """
        Назначение:
            Преобразовать ExecutionResult в DiagnosticItem.
        """
        code = map_system_code(result.error_code)
        details = {
            "status_code": result.status_code,
            "error_code": result.error_code.value if result.error_code else None,
            "error_reason": result.error_reason,
            "error_details": result.error_details,
        }
        return self.factory.error(
            stage=stage,
            code=code,
            field=None,
            message=result.error_message or "request failed",
            record_ref=None,
            details=details,
        )

    def system_code_of(self, diag: DiagnosticItem) -> SystemErrorCode:
        """
        Назначение:
            Получить системный код для диагностики.
        """
        return self.catalog.classify(diag.code)
