from __future__ import annotations

import time
from typing import Any, Iterator

import httpx

from .errors import AppError


class ApiError(AppError):
    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        body_snippet: str | None = None,
        retryable: bool = False,
        details: dict | None = None,
        code: str | None = None,
    ):
        super().__init__(
            category="api",
            code=code or (f"HTTP_{status_code}" if status_code else "API_ERROR"),
            message=message,
            retryable=retryable,
            details=details or {},
        )
        self.status_code = status_code
        self.body_snippet = body_snippet


class AnkeyApiClient:
    def __init__(
        self,
        baseUrl: str,
        username: str,
        password: str,
        timeoutSeconds: float = 20.0,
        tlsSkipVerify: bool = False,
        caFile: str | None = None,
        retries: int = 3,
        retryBackoffSeconds: float = 0.5,
        transport: httpx.BaseTransport | None = None,
    ):
        verify: bool | str = True
        if tlsSkipVerify:
            verify = False
        elif caFile:
            verify = caFile

        self.baseUrl = baseUrl.rstrip("/")
        self.username = username
        self.password = password
        self.retries = retries
        self.retryBackoffSeconds = retryBackoffSeconds
        self.retry_attempts = 0

        self.client = httpx.Client(
            base_url=self.baseUrl,
            timeout=timeoutSeconds,
            verify=verify,
            transport=transport,
        )

    def resetRetryAttempts(self) -> None:
        self.retry_attempts = 0

    def getRetryAttempts(self) -> int:
        return self.retry_attempts

    def _headers(self) -> dict[str, str]:
        return {
            "accept": "application/json",
            "X-Ankey-Username": self.username,
            "X-Ankey-Password": self.password,
            "X-Ankey-NoSession": "true",
        }

    def _should_retry(self, resp: httpx.Response) -> bool:
        if resp.status_code == 429:
            return True
        if 500 <= resp.status_code <= 599:
            return True
        return False

    def _sleep_backoff(self, attempt: int) -> None:
        delay = self.retryBackoffSeconds * (2 ** attempt)
        time.sleep(delay)

    def _request_with_retry(self, path: str, params: dict[str, Any]) -> httpx.Response:
        attempt = 0
        while True:
            try:
                resp = self.client.get(path, params=params, headers=self._headers())
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.retries:
                    raise ApiError("Network error", status_code=None, retryable=False) from exc
                self.retry_attempts += 1
                self._sleep_backoff(attempt)
                attempt += 1
                continue

            if resp.status_code == 200:
                return resp

            if self._should_retry(resp) and attempt < self.retries:
                self.retry_attempts += 1
                self._sleep_backoff(attempt)
                attempt += 1
                continue

            body_snippet = resp.text[:200] if resp.text else None
            raise ApiError(
                f"HTTP {resp.status_code}",
                status_code=resp.status_code,
                body_snippet=body_snippet,
                retryable=self._should_retry(resp),
                details={"body_snippet": body_snippet},
            )

    def getJson(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        resp = self._request_with_retry(path, params)
        try:
            return resp.json()
        except ValueError as exc:
            raise ApiError("Invalid JSON response", status_code=resp.status_code, retryable=False) from exc

    def requestJson(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        jsonBody: Any | None = None,
    ) -> tuple[int, Any]:
        params = params or {}
        attempt = 0
        while True:
            try:
                resp = self.client.request(method, path, params=params, headers=self._headers(), json=jsonBody)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt >= self.retries:
                    raise ApiError("Network error", status_code=None, retryable=False) from exc
                self.retry_attempts += 1
                self._sleep_backoff(attempt)
                attempt += 1
                continue

            if resp.status_code in (200, 201, 204):
                if resp.text:
                    try:
                        return resp.status_code, resp.json()
                    except ValueError:
                        return resp.status_code, resp.text
                return resp.status_code, None

            if self._should_retry(resp) and attempt < self.retries:
                self.retry_attempts += 1
                self._sleep_backoff(attempt)
                attempt += 1
                continue

            body_snippet = resp.text[:200] if resp.text else None
            raise ApiError(
                f"HTTP {resp.status_code}",
                status_code=resp.status_code,
                body_snippet=body_snippet,
                retryable=self._should_retry(resp),
                details={"body_snippet": body_snippet},
            )

    def _extract_items(self, data: Any) -> list[Any]:
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for key in ("items", "data", "users", "organizations", "orgs", "result"):
                if key in data and isinstance(data[key], list):
                    return data[key]
        raise ApiError("Unexpected response format: no items array")

    def getPagedItems(self, path: str, pageSize: int, maxPages: int | None) -> Iterator[tuple[int, list[Any]]]:
        """
        Возвращает пары (page_number, items) постранично.
        """
        page = 1
        while True:
            if maxPages is not None and page > maxPages:
                raise ApiError("max pages exceeded", code="MAX_PAGES_EXCEEDED", status_code=None, retryable=False)
            params = {"page": page, "rows": pageSize, "_queryFilter": "true"}
            data = self.getJson(path, params=params)
            items = self._extract_items(data)
            if not items:
                break
            yield page, items
            if len(items) < pageSize:
                break
            page += 1
