"""Ankey HTTP-драйвер target-провайдера."""

from __future__ import annotations

from typing import Any, Iterator

from connector.infra.http.ankey_client import AnkeyApiClient, ApiError
from connector.infra.target.driver import DriverError, DriverResponse


class AnkeyHttpDriver:
    """
    Назначение:
        Адаптер AnkeyApiClient(retries=0) к TargetDriver-контракту.
        Делает ровно одну попытку, нормализует транспортные ошибки в DriverError.
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


__all__ = ["AnkeyHttpDriver"]
