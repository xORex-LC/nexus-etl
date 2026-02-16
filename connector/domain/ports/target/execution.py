"""
Назначение:
    Доменные порты для взаимодействия с target-системой.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from connector.domain.diagnostics.policies import SystemErrorCode


@dataclass
class RequestSpec:
    """
    Назначение:
        Унифицированная инструкция target-операции для слоя исполнения.

    Инварианты:
        - path-mode: method/path обязательны, expected_statuses не пуст.
        - operation-mode: operation_alias обязателен; method/path/expected_statuses
          не задаются, т.к. берутся строго из OperationSpec в target-core.
    """

    method: str | None = None
    path: str | None = None
    payload: Any | None = None
    headers: dict[str, str] | None = None
    query: dict[str, Any] | None = None
    expected_statuses: Sequence[int] = field(default_factory=tuple)
    operation_alias: str | None = None
    operation_params: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.operation_alias is not None:
            alias = self.operation_alias.strip()
            if alias == "":
                raise ValueError("operation_alias must not be empty")
            self.operation_alias = alias
            if self.method is not None or self.path is not None:
                raise ValueError("method/path must be omitted when operation_alias is set")
            if self.expected_statuses:
                raise ValueError("expected_statuses must be omitted when operation_alias is set")
            return

        if not self.method:
            raise ValueError("method is required when operation_alias is not set")
        if not self.path:
            raise ValueError("path is required when operation_alias is not set")
        self.method = self.method.upper()
        if not self.expected_statuses:
            raise ValueError("expected_statuses must not be empty")

    @classmethod
    def post(
        cls,
        path: str,
        payload: Any | None = None,
        *,
        headers: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        expected_statuses: Sequence[int] = (201, 200),
    ) -> "RequestSpec":
        return cls(
            method="POST",
            path=path,
            payload=payload,
            headers=headers,
            query=query,
            expected_statuses=expected_statuses,
        )

    @classmethod
    def operation(
        cls,
        alias: str,
        *,
        payload: Any | None = None,
        headers: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> "RequestSpec":
        return cls(
            method=None,
            path=None,
            payload=payload,
            headers=headers,
            query=query,
            expected_statuses=tuple(),
            operation_alias=alias,
            operation_params=params,
        )

    @classmethod
    def put(
        cls,
        path: str,
        payload: Any | None = None,
        *,
        headers: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        expected_statuses: Sequence[int] = (200, 201),
    ) -> "RequestSpec":
        return cls(
            method="PUT",
            path=path,
            payload=payload,
            headers=headers,
            query=query,
            expected_statuses=expected_statuses,
        )

    @classmethod
    def patch(
        cls,
        path: str,
        payload: Any | None = None,
        *,
        headers: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        expected_statuses: Sequence[int] = (200, 204),
    ) -> "RequestSpec":
        return cls(
            method="PATCH",
            path=path,
            payload=payload,
            headers=headers,
            query=query,
            expected_statuses=expected_statuses,
        )

    @classmethod
    def delete(
        cls,
        path: str,
        *,
        headers: dict[str, str] | None = None,
        query: dict[str, Any] | None = None,
        expected_statuses: Sequence[int] = (200, 204),
    ) -> "RequestSpec":
        return cls(
            method="DELETE",
            path=path,
            payload=None,
            headers=headers,
            query=query,
            expected_statuses=expected_statuses,
        )

    def is_expected(self, status_code: int | None) -> bool:
        """
        Назначение:
            Проверить, входит ли статус в список допустимых.
        """
        if not self.expected_statuses:
            return False
        return status_code in self.expected_statuses


@dataclass
class ExecutionResult:
    """
    Назначение:
        Нормализованный результат исполнения RequestSpec.
    """

    ok: bool
    status_code: int | None
    response_json: Any | None = None
    error_code: SystemErrorCode | None = None
    error_message: str | None = None
    error_reason: str | None = None
    error_details: dict[str, Any] | None = None


class RequestExecutorProtocol(Protocol):
    """
    Назначение:
        Порт исполнения HTTP-запросов для use-case import-apply.
    """

    def execute(self, spec: RequestSpec) -> ExecutionResult: ...
