from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence

from connector.domain.error_codes import ErrorCode


@dataclass
class RequestSpec:
    """
    Назначение:
        Унифицированная инструкция HTTP-запроса для слоя исполнения.

    Инварианты:
        - method хранится в upper-case.
        - expected_statuses не пуст.
    """

    method: str
    path: str
    payload: Any | None = None
    headers: dict[str, str] | None = None
    query: dict[str, Any] | None = None
    expected_statuses: Sequence[int] = field(default_factory=tuple)

    def __post_init__(self) -> None:
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
    error_code: ErrorCode | None = None
    error_message: str | None = None
    error_reason: str | None = None
    error_details: dict[str, Any] | None = None


class RequestExecutorProtocol(Protocol):
    """
    Назначение:
        Порт исполнения HTTP-запросов для use-case import-apply.
    """

    def execute(self, spec: RequestSpec) -> ExecutionResult: ...
