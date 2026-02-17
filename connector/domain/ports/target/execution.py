"""
Назначение:
    Доменные порты для взаимодействия с target-системой.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Literal, Protocol

from connector.domain.diagnostics.policies import SystemErrorCode

ResponsePayloadFormat = Literal[
    "none",
    "json",
    "text",
    "bytes",
    "rows",
    "object",
]


def infer_response_payload_format(payload: Any) -> ResponsePayloadFormat:
    """Определить формат полезной нагрузки для нейтрального ответа."""
    if payload is None:
        return "none"
    if isinstance(payload, (dict, list)):
        return "json"
    if isinstance(payload, str):
        return "text"
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return "bytes"
    return "object"


@dataclass(frozen=True, slots=True)
class RequestSpec:
    """
    Назначение:
        Унифицированный intent на выполнение target-операции.

    Контракт:
        - operation_alias обязателен;
        - operation_params содержит параметры operation alias;
        - payload содержит бизнес-данные операции.
    """

    operation_alias: str
    payload: Any | None = None
    operation_params: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        alias = self.operation_alias.strip()
        if alias == "":
            raise ValueError("operation_alias must not be empty")
        object.__setattr__(self, "operation_alias", alias)
        if self.operation_params is not None:
            object.__setattr__(self, "operation_params", dict(self.operation_params))

    @classmethod
    def operation(
        cls,
        alias: str,
        *,
        payload: Any | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> "RequestSpec":
        return cls(
            operation_alias=alias,
            payload=payload,
            operation_params=params,
        )


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """
    Назначение:
        Нормализованный результат исполнения RequestSpec.
    """

    ok: bool
    answer_code: int | str | None = None
    response_payload: Any | None = None
    response_format: ResponsePayloadFormat = "none"
    error_code: SystemErrorCode | None = None
    error_message: str | None = None
    error_reason: str | None = None
    error_details: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        response_payload = self.response_payload
        if self.response_format == "none" and response_payload is not None:
            object.__setattr__(
                self,
                "response_format",
                infer_response_payload_format(response_payload),
            )

        if self.error_details is not None:
            object.__setattr__(self, "error_details", dict(self.error_details))


class RequestExecutorProtocol(Protocol):
    """
    Назначение:
        Порт исполнения target-операций для use-case apply.
    """

    def execute(self, spec: RequestSpec) -> ExecutionResult: ...
