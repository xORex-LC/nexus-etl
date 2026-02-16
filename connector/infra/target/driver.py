"""
TargetDriver — single-attempt transport.

Назначение:
    Низкоуровневый I/O к target-системе. Выполняет ровно одну попытку.
    Не содержит policy-retry (это ответственность TargetGateway).

Контракт:
    - DriverError: transport-ошибки (сеть, таймаут).
    - DriverResponse: результат успешного HTTP-обмена (любой статус).
    - ApiError с кодом != NETWORK_ERROR: возвращается как DriverResponse
      (Gateway классифицирует по status_code).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterator, Protocol

from connector.infra.http.ankey_client import AnkeyApiClient, ApiError


@dataclass(frozen=True, slots=True)
class DriverResponse:
    """Результат одной I/O попытки."""

    status_code: int
    body: Any
    body_snippet: str | None


class DriverError(Exception):
    """Transport-ошибка (network, timeout). Не содержит HTTP-статуса."""

    def __init__(self, message: str, code: str = "NETWORK_ERROR") -> None:
        super().__init__(message)
        self.code = code


class TargetDriver(Protocol):
    """Протокол single-attempt transport."""

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


class AnkeyHttpDriver:
    """
    Назначение:
        Адаптер AnkeyApiClient(retries=0) к TargetDriver.
        Делает ровно одну попытку, нормализует transport-ошибки в DriverError.
    """

    def __init__(self, client: AnkeyApiClient) -> None:
        self._client = client

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> DriverResponse:
        try:
            status, body, snippet = self._client.requestAny(
                method, path, params, json, headers,
            )
            return DriverResponse(status_code=status, body=body, body_snippet=snippet)
        except ApiError as exc:
            if exc.code == "NETWORK_ERROR":
                raise DriverError(str(exc), code="NETWORK_ERROR") from exc
            return DriverResponse(
                status_code=exc.status_code or 0,
                body=None,
                body_snippet=exc.body_snippet,
            )

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            return self._client.getJson(path, params)
        except ApiError as exc:
            if exc.code == "NETWORK_ERROR":
                raise DriverError(str(exc), code="NETWORK_ERROR") from exc
            raise

    def get_paged_items(
        self,
        path: str,
        page_size: int,
        max_pages: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]:
        return self._client.getPagedItems(path, page_size, max_pages, params=params)
