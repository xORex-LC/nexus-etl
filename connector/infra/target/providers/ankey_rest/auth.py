"""HTTP-адаптер аутентификации для провайдера Ankey REST."""

from __future__ import annotations

import httpx


class AnkeyAuth(httpx.Auth):
    """Добавляет статические заголовки аутентификации Ankey в каждый запрос."""

    def __init__(self, *, username: str, password: str) -> None:
        self._username = username
        self._password = password

    def auth_flow(self, request: httpx.Request):  # type: ignore[override]
        request.headers["X-Ankey-Username"] = self._username
        request.headers["X-Ankey-Password"] = self._password
        request.headers["X-Ankey-NoSession"] = "true"
        request.headers.setdefault("accept", "application/json")
        yield request


__all__ = ["AnkeyAuth"]
