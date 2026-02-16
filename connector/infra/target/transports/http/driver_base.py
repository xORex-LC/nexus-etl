"""Базовый протокол HTTP-драйвера транспорта (без привязки к провайдеру)."""

from __future__ import annotations

from typing import Any, Protocol

from connector.infra.target.driver import DriverResponse


class HttpDriverBase(Protocol):
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> DriverResponse: ...
