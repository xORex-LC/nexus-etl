"""
TargetDriver — транспорт с одной попыткой выполнения.

Назначение:
    Низкоуровневый I/O к target-системе. Выполняет ровно одну попытку.
    Не содержит политики повторов (это ответственность TargetGateway).

Контракт:
    - DriverError: транспортные ошибки (сеть, таймаут).
    - DriverResponse: результат успешного HTTP-обмена (любой статус).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Protocol


@dataclass(frozen=True, slots=True)
class DriverResponse:
    """Результат одной I/O попытки."""

    status_code: int
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
    """Протокол транспорта с одной попыткой."""

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> DriverResponse: ...

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any: ...

    def get_paged_items(
        self,
        path: str,
        page_size: int,
        max_pages: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]: ...

    def close(self) -> None: ...
