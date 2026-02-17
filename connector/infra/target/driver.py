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
from typing import Any, Iterator, Protocol


@dataclass(frozen=True, slots=True)
class DriverResponse:
    """Результат одной I/O попытки."""

    ok: bool              # драйвер определяет успех по своей транспортной логике
    status_code: int | None  # HTTP-статус или None для не-HTTP транспортов (для диагностики)
    body: Any
    body_snippet: str | None


class DriverError(Exception):
    """Транспортная/протокольная ошибка одной попытки I/O."""

    def __init__(
        self,
        message: str,
        code: str = "NETWORK_ERROR",
        *,
        status_code: int | None = None,
        body_snippet: str | None = None,
        details: dict[str, Any] | None = None,
        retry_after_s: float | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.body_snippet = body_snippet
        self.details = details or {}
        self.retry_after_s = retry_after_s


class TargetDriver(Protocol):
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
        compiled_request: Any,
        payload: Any | None = None,
    ) -> DriverResponse: ...

    def iter_batches(
        self,
        compiled_request: Any,
        batch_size: int,
        max_batches: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]: ...

    def close(self) -> None: ...
