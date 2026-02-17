"""
TargetDriver — транспорт с одной попыткой выполнения.

Назначение:
    Низкоуровневый I/O к target-системе. Выполняет ровно одну попытку.
    Не содержит политики повторов (это ответственность TargetGateway).

Контракт:
    - DriverError: транспортные ошибки (сеть, таймаут, протокол).
    - DriverResponse: результат I/O попытки (ok определяется драйвером).
    - execute: однократное выполнение скомпилированной операции с payload.
    - iter_batches: постраничное/пакетное чтение.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Protocol, TypeVar

from connector.domain.ports.target.execution import (
    ResponsePayloadFormat,
    infer_response_payload_format,
)

TCompiledRequest = TypeVar("TCompiledRequest", contravariant=True)


@dataclass(frozen=True, slots=True)
class DriverResponse:
    """Результат одной I/O попытки."""

    ok: bool              # драйвер определяет успех по своей транспортной логике
    answer_code: int | str | None = None
    payload: Any = None
    content_preview: str | None = None
    payload_format: ResponsePayloadFormat = "none"
    error_reason: str | None = None
    retry_after_s: float | None = None

    def __post_init__(self) -> None:
        if self.payload_format == "none" and self.payload is not None:
            object.__setattr__(
                self,
                "payload_format",
                infer_response_payload_format(self.payload),
            )


class DriverError(Exception):
    """Транспортная/протокольная ошибка одной попытки I/O."""

    def __init__(
        self,
        message: str,
        code: str = "NETWORK_ERROR",
        *,
        answer_code: int | str | None = None,
        content_preview: str | None = None,
        details: dict[str, Any] | None = None,
        retry_after_s: float | None = None,
        error_reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.answer_code = answer_code
        self.content_preview = content_preview
        self.details = details or {}
        self.retry_after_s = retry_after_s
        self.error_reason = error_reason


class TargetDriver(Protocol[TCompiledRequest]):
    """Транспорт-агностичный протокол с одной попыткой I/O.

    Контракт:
        - execute: однократное выполнение операции. Принимает скомпилированный
          запрос (opaque для gateway) и опциональный payload.
          Драйвер знает тип compiled_request и работает с ним напрямую.
        - iter_batches: постраничное/пакетное чтение. Драйвер управляет
          стратегией итерации (offset/limit, cursor и т.д.).
        - Поднимает DriverError при транспортных/протокольных ошибках.
        - Не содержит политики повторов.
    """

    def execute(
        self,
        compiled_request: TCompiledRequest,
        payload: Any | None = None,
    ) -> DriverResponse: ...

    def iter_batches(
        self,
        compiled_request: TCompiledRequest,
        batch_size: int,
        max_batches: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]: ...

    def close(self) -> None: ...
