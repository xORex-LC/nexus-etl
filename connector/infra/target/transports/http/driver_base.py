"""Базовый протокол HTTP transport request_once контракта."""

from __future__ import annotations

from typing import Protocol

import httpx

from connector.infra.target.transports.http.request_builder import HttpRequest
from connector.infra.target.transports.http.request_once import HttpOutcome


class HttpRequestOncePort(Protocol):
    def __call__(self, client: httpx.Client, req: HttpRequest) -> HttpOutcome: ...
