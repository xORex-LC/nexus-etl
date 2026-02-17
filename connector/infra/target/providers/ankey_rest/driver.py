"""HTTP-драйвер провайдера Ankey для целевого слоя."""

from __future__ import annotations

from typing import Any, Iterator

import httpx

from connector.infra.target.driver import DriverError, DriverResponse
from connector.infra.target.transports.http.normalizer import normalize_http_outcome
from connector.infra.target.transports.http.request_builder import HttpRequest
from connector.infra.target.transports.http.request_once import request_once


class AnkeyHttpDriver:
    """
    Назначение:
        HTTP-драйвер Ankey поверх общего transport/http.
        Делает ровно одну попытку на каждый запрос.
        Реализует TargetDriver protocol: execute + iter_batches.
    """

    def __init__(self, client: httpx.Client) -> None:
        self._client = client

    def execute(
        self,
        compiled_request: Any,
        payload: Any | None = None,
    ) -> DriverResponse:
        """Выполнить одну операцию. compiled_request — HttpRequest."""
        req: HttpRequest = compiled_request
        outcome = request_once(
            self._client,
            HttpRequest(
                method=req.method,
                path=req.path,
                query=req.query,
                headers=req.headers,
                json=payload,
                timeout_s=req.timeout_s,
                expected_statuses=req.expected_statuses,
            ),
        )
        normalized = normalize_http_outcome(outcome)
        if normalized.error_code is not None:
            raise DriverError(
                normalized.error_message or normalized.error_code,
                code=normalized.error_code,
            )
        if normalized.status_code is None:
            raise DriverError("empty http response", code="HTTP_OUTCOME_EMPTY")
        ok = normalized.status_code in req.expected_statuses
        return DriverResponse(
            ok=ok,
            status_code=normalized.status_code,
            body=normalized.body,
            body_snippet=normalized.body_snippet,
        )

    def iter_batches(
        self,
        compiled_request: Any,
        batch_size: int,
        max_batches: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]:
        """Итерация по страницам. compiled_request — HttpRequest (должен быть GET)."""
        req: HttpRequest = compiled_request
        base_query = dict(req.query)
        if params:
            base_query.update(params)
        base_query.setdefault("_queryFilter", "true")
        page = 1
        while True:
            if max_batches is not None and page > max_batches:
                raise DriverError(
                    "max pages exceeded",
                    code="MAX_PAGES_EXCEEDED",
                )
            request_params = {**base_query, "page": page, "rows": batch_size}
            iter_req = HttpRequest(
                method=req.method,
                path=req.path,
                query=request_params,
                headers=req.headers,
                json=None,
                timeout_s=req.timeout_s,
                expected_statuses=req.expected_statuses,
            )
            outcome = request_once(self._client, iter_req)
            normalized = normalize_http_outcome(outcome)
            if normalized.error_code is not None:
                raise DriverError(
                    normalized.error_message or normalized.error_code,
                    code=normalized.error_code,
                    status_code=normalized.status_code,
                )
            if normalized.status_code not in req.expected_statuses:
                raise DriverError(
                    f"HTTP {normalized.status_code}",
                    code=f"HTTP_{normalized.status_code}",
                    status_code=normalized.status_code,
                    body_snippet=normalized.body_snippet,
                    details={"body_snippet": normalized.body_snippet}
                    if normalized.body_snippet
                    else None,
                )

            items = _extract_items(normalized.body)
            if not items:
                break
            yield page, items
            if len(items) < batch_size:
                break
            page += 1

    def close(self) -> None:
        self._client.close()


def _extract_items(data: Any) -> list[Any]:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "data", "users", "organizations", "orgs", "result"):
            if key in data and isinstance(data[key], list):
                return data[key]
    raise DriverError(
        "Unexpected response format: no items array",
        code="INVALID_ITEMS_FORMAT",
    )


__all__ = ["AnkeyHttpDriver"]
