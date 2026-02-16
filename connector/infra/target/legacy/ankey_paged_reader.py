from __future__ import annotations

from typing import Any, Iterable

from connector.common.sanitize import maskSecretsInObject, truncateText
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.diagnostics.policies import map_http_status
from connector.domain.ports.target.read import TargetPageResult, TargetPagedReaderProtocol
from connector.infra.http.ankey_client import AnkeyApiClient, ApiError
from connector.infra.target.spec_ankey import build_ankey_spec


def _default_read_operation_paths() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for alias, operation in build_ankey_spec().operations.items():
        if operation.http is None:
            continue
        if operation.http.method != "GET":
            continue
        if not alias.endswith(".list"):
            continue
        if "{" in operation.http.path_template:
            continue
        mapping[alias] = operation.http.path_template
    return mapping


_DEFAULT_READ_OPERATION_PATHS = _default_read_operation_paths()


class AnkeyTargetPagedReader(TargetPagedReaderProtocol):
    """
    Назначение/ответственность:
        Legacy-адаптер чтения страниц из Ankey API.
    Взаимодействия:
        Использует AnkeyApiClient, нормализует ошибки в TargetPageResult.
    """

    def __init__(
        self,
        client: AnkeyApiClient,
        *,
        operation_paths: dict[str, str] | None = None,
    ):
        self.client = client
        self._operation_paths = dict(operation_paths or _DEFAULT_READ_OPERATION_PATHS)

    def iter_pages(
        self,
        operation_alias: str,
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
        path: str
        if operation_alias.startswith("/"):
            path = operation_alias
        else:
            path = self._operation_paths.get(operation_alias, "")
        if not path:
            yield TargetPageResult(
                ok=False,
                page=last_page,
                items=None,
                error_code=SystemErrorCode.INTERNAL_ERROR,
                error_message=f"Unknown read operation alias: {operation_alias}",
            )
            return
        try:
            for page, items in self.client.getPagedItems(path, page_size, max_pages, params=params):
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
            error_code = map_http_status(status_code)
            if getattr(exc, "code", None) == "NETWORK_ERROR":
                error_code = SystemErrorCode.INFRA_UNAVAILABLE
            if getattr(exc, "code", None) == "INVALID_JSON":
                error_code = SystemErrorCode.IO_ERROR

            yield TargetPageResult(
                ok=False,
                page=last_page,
                items=None,
                error_code=error_code,
                error_message=str(exc),
                error_details=error_details or None,
            )


__all__ = ["AnkeyTargetPagedReader"]
