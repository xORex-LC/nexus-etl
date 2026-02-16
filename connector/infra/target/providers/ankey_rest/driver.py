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
    """

    def __init__(self, client: httpx.Client) -> None:
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
        outcome = request_once(
            self._client,
            HttpRequest(
                method=method,
                path=path,
                query=dict(params or {}),
                headers=dict(headers or {}),
                json=json,
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
        return DriverResponse(
            status_code=normalized.status_code,
            body=normalized.body,
            body_snippet=normalized.body_snippet,
        )

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        response = self.request("GET", path, params=params)
        if response.status_code != 200:
            raise DriverError(
                f"HTTP {response.status_code}",
                code=f"HTTP_{response.status_code}",
                status_code=response.status_code,
                body_snippet=response.body_snippet,
            )
        if isinstance(response.body, str):
            raise DriverError("Invalid JSON response", code="INVALID_JSON")
        return response.body

    def get_paged_items(
        self,
        path: str,
        page_size: int,
        max_pages: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]:
        base_params = dict(params or {})
        base_params.setdefault("_queryFilter", "true")
        page = 1
        while True:
            if max_pages is not None and page > max_pages:
                raise DriverError(
                    "max pages exceeded",
                    code="MAX_PAGES_EXCEEDED",
                )
            request_params = dict(base_params)
            request_params["page"] = page
            request_params["rows"] = page_size

            response = self.request("GET", path, params=request_params)
            if response.status_code != 200:
                raise DriverError(
                    f"HTTP {response.status_code}",
                    code=f"HTTP_{response.status_code}",
                    status_code=response.status_code,
                    body_snippet=response.body_snippet,
                    details={"body_snippet": response.body_snippet} if response.body_snippet else None,
                )

            items = _extract_items(response.body)
            if not items:
                break
            yield page, items
            if len(items) < page_size:
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
