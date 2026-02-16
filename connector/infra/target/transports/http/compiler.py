"""Компиляция HTTP-данных операции для HTTP-транспорта."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connector.infra.target.core.spec_models import OperationSpec
from connector.infra.target.transports.http.op_models import HttpOperationDataModel
from connector.infra.target.transports.http.request_builder import HttpRequest, build_http_request


@dataclass(frozen=True, slots=True)
class CompiledHttpOperation:
    """Скомпилированная HTTP-операция с валидированными transport-данными."""

    op_data: HttpOperationDataModel

    def build(
        self,
        *,
        alias: str,
        operation_params: dict[str, Any] | None = None,
        query_overrides: dict[str, Any] | None = None,
        header_overrides: dict[str, str] | None = None,
    ) -> HttpRequest:
        return build_http_request(
            alias=alias,
            op_data=self.op_data,
            operation_params=operation_params,
            query_overrides=query_overrides,
            header_overrides=header_overrides,
        )


def compile_http_operation_data(raw_data: dict[str, Any]) -> HttpOperationDataModel:
    """Провалидировать и вернуть HTTP-данные операции."""
    return HttpOperationDataModel.model_validate(raw_data)


def compile_http_operation(operation: OperationSpec) -> CompiledHttpOperation:
    """
    Скомпилировать и провалидировать HTTP-данные из OperationSpec.

    Важно:
        - transport-валидация сосредоточена здесь;
        - ядро не проверяет HTTP-детали напрямую.
    """
    if operation.kind != "http":
        raise ValueError(f"operation {operation.alias!r} is not http")
    if not operation.data:
        raise ValueError(f"operation {operation.alias!r} requires transport payload")
    return CompiledHttpOperation(op_data=compile_http_operation_data(operation.data))
