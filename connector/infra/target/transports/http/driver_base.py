"""Базовый HTTP-драйвер и порт однократного выполнения запроса."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Callable, Iterator, Protocol

import httpx

from connector.infra.target.driver import DriverError, DriverResponse, infer_response_payload_format
from connector.infra.target.transports.http.normalizer import normalize_http_outcome
from connector.infra.target.transports.http.paging import HttpPagingStrategy
from connector.infra.target.transports.http.request_builder import HttpRequest
from connector.infra.target.transports.http.request_once import HttpOutcome, request_once


class HttpRequestOncePort(Protocol):
    """Порт однократного выполнения HTTP-запроса."""

    def __call__(self, client: httpx.Client, req: HttpRequest) -> HttpOutcome: ...


class BaseHttpDriver:
    """
    Назначение:
        Транспортно-агностичный HTTP-драйвер поверх request_once.
        Реализует TargetDriver protocol (execute + iter_batches + close).
        Стратегия пагинации и опциональный детектор причин ошибок инжектируются.

    Контракт:
        - execute: однократный HTTP-запрос с payload; поднимает DriverError при
          транспортных сбоях, возвращает DriverResponse(ok=False) при не-ok статусе.
        - iter_batches: постраничное чтение через HttpPagingStrategy; поднимает
          DriverError при любой ошибке (включая не-ok статус).
        - Не содержит retry-логики — это ответственность TargetGateway.
    """

    def __init__(
        self,
        client: httpx.Client,
        paging: HttpPagingStrategy,
        *,
        error_reason_fn: Callable[[Any, str | None], str | None] | None = None,
        request_fn: HttpRequestOncePort = request_once,
    ) -> None:
        self._client = client
        self._paging = paging
        self._error_reason_fn = error_reason_fn
        self._request_fn = request_fn

    # ------------------------------------------------------------------
    # TargetDriver protocol
    # ------------------------------------------------------------------

    def execute(
        self,
        compiled_request: Any,
        payload: Any | None = None,
    ) -> DriverResponse:
        """Выполнить одну HTTP-операцию с опциональным payload."""
        req: HttpRequest = compiled_request
        outcome = self._request_fn(self._client, replace(req, json=payload))
        normalized = normalize_http_outcome(outcome)
        error_reason = self._resolve_error_reason(normalized.body, normalized.body_snippet)

        if normalized.error_code is not None:
            raise DriverError(
                normalized.error_message or normalized.error_code,
                code=normalized.error_code,
                answer_code=normalized.status_code,
                content_preview=normalized.body_snippet,
                retry_after_s=normalized.retry_after_s,
                error_reason=error_reason,
            )
        if normalized.status_code is None:
            raise DriverError("empty http response", code="HTTP_OUTCOME_EMPTY")

        return DriverResponse(
            ok=normalized.status_code in req.expected_statuses,
            answer_code=normalized.status_code,
            payload=normalized.body,
            content_preview=normalized.body_snippet,
            payload_format=infer_response_payload_format(normalized.body),
            error_reason=error_reason,
            retry_after_s=normalized.retry_after_s,
        )

    def iter_batches(
        self,
        compiled_request: Any,
        batch_size: int,
        max_batches: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]:
        """Постраничное чтение через HttpPagingStrategy."""
        req: HttpRequest = compiled_request
        base_req = replace(req, query={**req.query, **params}) if params else req

        page = 1
        while True:
            if max_batches is not None and page > max_batches:
                break

            page_req = self._paging.build_paged_request(base_req, page, batch_size)
            outcome = self._request_fn(self._client, page_req)
            normalized = normalize_http_outcome(outcome)
            error_reason = self._resolve_error_reason(normalized.body, normalized.body_snippet)

            if normalized.error_code is not None:
                raise DriverError(
                    normalized.error_message or normalized.error_code,
                    code=normalized.error_code,
                    answer_code=normalized.status_code,
                    content_preview=normalized.body_snippet,
                    retry_after_s=normalized.retry_after_s,
                    error_reason=error_reason,
                )
            if normalized.status_code not in req.expected_statuses:
                raise DriverError(
                    f"target answer {normalized.status_code}",
                    code=f"HTTP_{normalized.status_code}",
                    answer_code=normalized.status_code,
                    content_preview=normalized.body_snippet,
                    details={"content_preview": normalized.body_snippet} if normalized.body_snippet else None,
                    retry_after_s=normalized.retry_after_s,
                    error_reason=error_reason,
                )

            try:
                items = self._paging.extract_items(normalized.body)
            except ValueError as exc:
                raise DriverError(str(exc), code="INVALID_ITEMS_FORMAT") from exc

            if not items:
                break
            yield page, items
            if len(items) < batch_size:
                break
            page += 1

    def close(self) -> None:
        self._client.close()

    # ------------------------------------------------------------------
    # Внутренние вспомогательные методы
    # ------------------------------------------------------------------

    def _resolve_error_reason(self, body: Any, snippet: str | None) -> str | None:
        return self._error_reason_fn(body, snippet) if self._error_reason_fn else None
