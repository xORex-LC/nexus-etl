"""Компиляция HTTP operation data для transport HTTP."""

from __future__ import annotations

from typing import Any

from connector.infra.target.core.spec_models import OperationSpec
from connector.infra.target.transports.http.op_models import HttpOperationDataModel


def compile_http_operation_data(raw_data: dict[str, Any]) -> HttpOperationDataModel:
    """Провалидировать и вернуть HTTP operation data."""
    return HttpOperationDataModel.model_validate(raw_data)


def compile_http_operation(operation: OperationSpec) -> HttpOperationDataModel:
    """
    Скомпилировать и провалидировать HTTP operation data из OperationSpec.

    Важно:
        - transport-валидация сосредоточена здесь;
        - ядро не проверяет HTTP-детали напрямую.
    """
    if operation.kind != "http":
        raise ValueError(f"operation {operation.alias!r} is not http")
    if operation.http is None:
        raise ValueError(f"operation {operation.alias!r} requires http payload")
    return compile_http_operation_data(operation.http.model_dump())
