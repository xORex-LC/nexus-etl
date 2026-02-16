"""Выполнение одной HTTP-попытки для target-транспорта."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from connector.infra.target.transports.http.request_builder import HttpRequest

_BODY_SNIPPET_LIMIT = 200


@dataclass(frozen=True, slots=True)
class HttpResponsePayload:
    status_code: int
    headers: dict[str, str]
    body: Any | None
    body_snippet: str | None


@dataclass(frozen=True, slots=True)
class HttpErrorPayload:
    code: str
    message: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class HttpOutcome:
    response: HttpResponsePayload | None = None
    error: HttpErrorPayload | None = None


def _parse_body(response: httpx.Response) -> tuple[Any | None, str | None]:
    text = response.text if response.text else None
    body_snippet = text[:_BODY_SNIPPET_LIMIT] if text else None
    if not text:
        return None, body_snippet
    try:
        return response.json(), body_snippet
    except ValueError:
        return text, body_snippet


def request_once(client: httpx.Client, req: HttpRequest) -> HttpOutcome:
    """Выполнить одну HTTP-попытку без retry/backoff."""
    try:
        response = client.request(
            req.method,
            req.path,
            params=req.query or None,
            headers=req.headers or None,
            json=req.json,
            timeout=req.timeout_s,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        return HttpOutcome(
            error=HttpErrorPayload(
                code="NETWORK_ERROR",
                message=str(exc),
            ),
        )

    body, body_snippet = _parse_body(response)
    return HttpOutcome(
        response=HttpResponsePayload(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=body,
            body_snippet=body_snippet,
        ),
    )


__all__ = [
    "HttpErrorPayload",
    "HttpOutcome",
    "HttpResponsePayload",
    "request_once",
]
