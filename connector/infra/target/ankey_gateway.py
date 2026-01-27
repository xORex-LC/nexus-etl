from __future__ import annotations

from typing import Any, Iterable

from connector.common.sanitize import maskSecretsInObject, truncateText
from connector.domain.error_codes import ErrorCode
from connector.domain.ports.target_read import TargetPageResult, TargetPagedReaderProtocol
from connector.infra.http.ankey_client import AnkeyApiClient, ApiError


class AnkeyTargetPagedReader(TargetPagedReaderProtocol):
    """
    Назначение/ответственность:
        Адаптер чтения страниц из Ankey API.
    Взаимодействия:
        Использует AnkeyApiClient, нормализует ошибки в TargetPageResult.
    """

    def __init__(self, client: AnkeyApiClient):
        self.client = client

    def iter_pages(
        self,
        path: str,
        page_size: int,
        max_pages: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterable[TargetPageResult]:
        """
        Назначение:
            Итерация по страницам Ankey API без исключений наружу.
        Алгоритм:
            - Делегирует AnkeyApiClient.getPagedItems.
            - ApiError превращает в TargetPageResult(ok=False).
        """
        params = params or {}
        last_page = 0
        try:
            for page, items in self.client.getPagedItems(path, page_size, max_pages):
                last_page = page
                safe_items = maskSecretsInObject(items)
                yield TargetPageResult(ok=True, page=page, items=safe_items)
        except ApiError as exc:
            error_details = {}
            if isinstance(exc.details, dict):
                error_details = maskSecretsInObject(exc.details)
            body_snippet = exc.body_snippet or (error_details.get("body_snippet") if isinstance(error_details, dict) else None)
            if body_snippet is not None:
                error_details = dict(error_details or {})
                error_details["body_snippet"] = truncateText(str(body_snippet))

            status_code = getattr(exc, "status_code", None)
            error_code = ErrorCode.from_status(status_code) if status_code else ErrorCode.API_ERROR
            if getattr(exc, "code", None) == "NETWORK_ERROR":
                error_code = ErrorCode.NETWORK_ERROR
            if getattr(exc, "code", None) == "INVALID_JSON":
                error_code = ErrorCode.INVALID_JSON

            yield TargetPageResult(
                ok=False,
                page=last_page,
                items=None,
                error_code=error_code,
                error_message=str(exc),
                error_details=error_details or None,
            )
