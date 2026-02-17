"""
Назначение:
    Перевод внешних ошибок (HTTP/исключения) в DiagnosticItem.
"""

from __future__ import annotations

from typing import Any

from connector.domain.diagnostics.catalog import ErrorCatalog, build_error
from connector.domain.diagnostics.policies import SystemErrorCode, map_http_status, map_system_code
from connector.domain.models import DiagnosticItem, DiagnosticStage
from connector.domain.ports.target.execution import ExecutionResult


def translate_exception(
    catalog: ErrorCatalog,
    stage: DiagnosticStage,
    exc: Exception,
    record_ref=None,
) -> DiagnosticItem:
    """
    Назначение:
        Преобразовать исключение в DiagnosticItem.
    """
    return build_error(
        catalog=catalog,
        stage=stage,
        code="INTERNAL_ERROR",
        field=None,
        message=str(exc),
        record_ref=record_ref,
        details=None,
    )


def translate_http(
    catalog: ErrorCatalog,
    stage: DiagnosticStage,
    status: int | None,
    body: Any | None,
    record_ref=None,
) -> DiagnosticItem:
    """
    Назначение:
        Преобразовать HTTP-ответ в DiagnosticItem.
    """
    system_code = map_http_status(status) if status is not None else None
    code = map_system_code(system_code)
    message = f"HTTP {status}" if status is not None else "HTTP error"
    details = {
        "status": status,
        "body": body,
        "system_code": system_code.value if system_code else None,
    } if status is not None or body is not None else None
    return build_error(
        catalog=catalog,
        stage=stage,
        code=code,
        field=None,
        message=message,
        record_ref=record_ref,
        details=details,
    )


def translate_execution_result(
    catalog: ErrorCatalog,
    stage: DiagnosticStage,
    result: ExecutionResult,
    record_ref=None,
) -> DiagnosticItem:
    """
    Назначение:
        Преобразовать ExecutionResult в DiagnosticItem.
    """
    code = map_system_code(result.error_code)
    details = {
        "answer_code": result.answer_code,
        "response_format": result.response_format,
        "error_code": result.error_code.value if result.error_code else None,
        "error_reason": result.error_reason,
        "error_details": result.error_details,
    }
    return build_error(
        catalog=catalog,
        stage=stage,
        code=code,
        field=None,
        message=result.error_message or "request failed",
        record_ref=record_ref,
        details=details,
    )


def system_code_of(catalog: ErrorCatalog, diag: DiagnosticItem) -> SystemErrorCode:
    """
    Назначение:
        Получить системный код для диагностики.
    """
    return catalog.classify(diag.code)
