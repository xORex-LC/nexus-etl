"""HTTP-драйвер провайдера Ankey для целевого слоя."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx

from connector.infra.target.transports.http.driver_base import BaseHttpDriver
from connector.infra.target.transports.http.request_builder import HttpRequest


class AnkeyPagingStrategy:
    """
    Стратегия пагинации для Ankey REST API.

    Использует page/rows параметры и _queryFilter=true.
    Извлекает элементы из Ankey-специфичных ключей ответа.
    """

    _ITEMS_KEYS: tuple[str, ...] = ("items", "data", "users", "organizations", "orgs", "result")

    def build_paged_request(
        self,
        base_req: HttpRequest,
        page: int,
        batch_size: int,
    ) -> HttpRequest:
        query = {**base_req.query, "page": page, "rows": batch_size}
        query.setdefault("_queryFilter", "true")
        return replace(base_req, query=query)

    def extract_items(self, body: Any) -> list[Any]:
        """Raises: ValueError если формат ответа не распознан."""
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            for key in self._ITEMS_KEYS:
                if key in body and isinstance(body[key], list):
                    return body[key]
        raise ValueError("Unexpected response format: no items array")


def _detect_ankey_error_reason(payload: Any, content_preview: str | None) -> str | None:
    """Определить provider-specific причину ошибки по содержимому ответа."""
    haystacks: list[str] = []
    if isinstance(payload, str):
        haystacks.append(payload)
    if isinstance(payload, dict):
        haystacks.extend(str(v) for v in payload.values())
    if content_preview:
        haystacks.append(content_preview)
    joined = " ".join(haystacks).lower()
    if "resourceexists" in joined or "resource exists" in joined:
        return "resourceexists"
    return None


def AnkeyHttpDriver(client: httpx.Client) -> BaseHttpDriver:
    """Фабрика HTTP-драйвера для Ankey REST API."""
    return BaseHttpDriver(
        client=client,
        paging=AnkeyPagingStrategy(),
        error_reason_fn=_detect_ankey_error_reason,
    )


__all__ = ["AnkeyHttpDriver"]
