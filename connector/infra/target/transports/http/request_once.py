"""Выполнение одной HTTP-попытки для target-транспорта."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

import httpx

from connector.infra.target.transports.http.request_builder import HttpRequest

_BODY_SNIPPET_LIMIT = 200


@dataclass(frozen=True, slots=True)
class HttpResponsePayload:
    """Данные HTTP-ответа, полученные за одну попытку запроса."""

    status_code: int
    headers: dict[str, str]
    body: Any | None
    body_snippet: str | None


@dataclass(frozen=True, slots=True)
class HttpErrorPayload:
    """Нормализованная transport-ошибка однократной HTTP-попытки."""

    code: str
    message: str
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class HttpOutcome:
    """Результат одной HTTP-попытки: либо ``response``, либо ``error``."""

    response: HttpResponsePayload | None = None
    error: HttpErrorPayload | None = None


def _parse_body(response: httpx.Response) -> tuple[Any | None, str | None]:
    """Распарсить body как JSON, а при невалидном JSON вернуть текст."""
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
    _emit_target_request_trace(
        method=req.method,
        path=req.path,
        query=req.query,
        headers=req.headers,
        body=req.json,
    )
    try:
        response = client.request(
            req.method,
            req.path,
            params=req.query or None,
            headers=req.headers or None,
            json=req.json,
            timeout=req.timeout_s if req.timeout_s is not None else httpx.USE_CLIENT_DEFAULT,
        )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        return HttpOutcome(
            error=HttpErrorPayload(
                code="NETWORK_ERROR",
                message=str(exc),
            ),
        )

    body, body_snippet = _parse_body(response)
    _emit_target_response_trace(
        method=req.method,
        path=req.path,
        status_code=response.status_code,
        headers=dict(response.headers),
        body=body,
    )
    return HttpOutcome(
        response=HttpResponsePayload(
            status_code=response.status_code,
            headers=dict(response.headers),
            body=body,
            body_snippet=body_snippet,
        ),
    )


def _emit_target_response_trace(
    *,
    method: str,
    path: str,
    status_code: int,
    headers: dict[str, str],
    body: Any,
) -> None:
    """
    Временный диагностический trace полного ответа target API.

    Почему через print:
        stdout/stderr в CLI рантайме уже tee'ятся в command log, поэтому это
        самый короткий и надёжный путь быстро увидеть полный ответ в логе без
        дополнительного wiring логгеров по target-layer.
    """
    try:
        serialized_body = json.dumps(body, ensure_ascii=False, default=str)
    except Exception:
        serialized_body = repr(body)
    try:
        serialized_headers = json.dumps(headers, ensure_ascii=False, default=str)
    except Exception:
        serialized_headers = repr(headers)
    print(
        "TARGET_HTTP_RESPONSE "
        f"method={method} path={path} status={status_code} "
        f"headers={serialized_headers} body={serialized_body}"
    )


def _emit_target_request_trace(
    *,
    method: str,
    path: str,
    query: dict[str, Any] | None,
    headers: dict[str, str] | None,
    body: Any,
) -> None:
    """
    Временный диагностический trace полного исходящего HTTP-запроса к target API.
    """
    try:
        serialized_query = json.dumps(query, ensure_ascii=False, default=str)
    except Exception:
        serialized_query = repr(query)
    try:
        serialized_headers = json.dumps(headers, ensure_ascii=False, default=str)
    except Exception:
        serialized_headers = repr(headers)
    try:
        serialized_body = json.dumps(body, ensure_ascii=False, default=str)
    except Exception:
        serialized_body = repr(body)
    print(
        "TARGET_HTTP_REQUEST "
        f"method={method} path={path} query={serialized_query} "
        f"headers={serialized_headers} body={serialized_body}"
    )


__all__ = [
    "HttpErrorPayload",
    "HttpOutcome",
    "HttpResponsePayload",
    "request_once",
]
