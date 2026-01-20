from __future__ import annotations

import time
from typing import Any

from connector.common.sanitize import maskSecretsInObject, truncateText
from connector.domain.error_codes import ErrorCode
from connector.domain.ports.execution import ExecutionResult, RequestExecutorProtocol, RequestSpec
from connector.infra.http.ankey_client import AnkeyApiClient, ApiError


class AnkeyRequestExecutor(RequestExecutorProtocol):
    """
    Назначение/ответственность:
        Адаптер RequestExecutorProtocol поверх AnkeyApiClient.
        Выполняет RequestSpec, нормализует результат и маскирует чувствительные данные.
    Ограничения:
        - Синхронное выполнение, одна попытка (retry управляется самим клиентом).
        - expected_statuses проверяются здесь, клиент их не знает.
    """

    def __init__(self, client: AnkeyApiClient, timeout_seconds: float | None = None):
        self._client = client
        self._timeout_seconds = timeout_seconds

    def execute(self, request: RequestSpec) -> ExecutionResult:
        """
        Контракт (вход/выход):
            Вход: RequestSpec.
            Выход: ExecutionResult c признаком ok, статусом и ошибкой/данными.
        Алгоритм:
            - Делегирует вызов AnkeyApiClient.requestAny.
            - Сравнивает status_code с expected_statuses.
            - Санитайзит response_json/error_message.
            - Ошибки клиента маппит в ExecutionResult с error_code.
        """
        start = time.perf_counter()
        try:
            status_code, response_json, body_snippet = self._client.requestAny(
                method=request.method,
                path=request.path,
                params=request.query,
                json=request.json,
                headers=request.headers,
                timeout=self._timeout_seconds,
            )
            ok = status_code in request.expected_statuses
            error_code: str | None = None if ok else ErrorCode.HTTP_UNEXPECTED_STATUS
            error_message: str | None = None
            if not ok:
                base_msg = body_snippet or f"Unexpected status {status_code}"
                error_message = truncateText(base_msg)
            return ExecutionResult(
                ok=ok,
                status_code=status_code,
                error_code=error_code,
                error_message=error_message,
                attempts=1,
                duration_ms=int((time.perf_counter() - start) * 1000),
                response_json=maskSecretsInObject(response_json) if response_json is not None else None,
            )
        except ApiError as err:
            return self._from_api_error(err, start)

    def _from_api_error(self, err: ApiError, start: float) -> ExecutionResult:
        """
        Назначение:
            Преобразует ApiError в ExecutionResult с унифицированными кодами/сообщениями.
        """
        status_code = getattr(err, "status_code", None)
        error_code = self._map_error_code(err.code, status_code)
        msg_parts: list[str] = []
        if err.message:
            msg_parts.append(err.message)
        snippet = getattr(err, "body_snippet", None)
        if snippet:
            msg_parts.append(snippet)
        error_message = truncateText(" | ".join(msg_parts) if msg_parts else None)
        response_json: Any | None = None
        details = getattr(err, "details", None)
        if isinstance(details, dict):
            response_json = maskSecretsInObject(details)
        return ExecutionResult(
            ok=False,
            status_code=status_code,
            error_code=error_code,
            error_message=error_message,
            attempts=1,
            duration_ms=int((time.perf_counter() - start) * 1000),
            response_json=response_json,
        )

    def _map_error_code(self, code: str | None, status_code: int | None) -> str:
        """
        Алгоритм:
            - Маппит известные коды в ErrorCode.
            - Для HTTP_* использует статус, чтобы выбрать 4xx/5xx/UNEXPECTED.
            - Возвращает UNKNOWN_ERROR по умолчанию.
        """
        if not code:
            return ErrorCode.UNKNOWN_ERROR
        if code == "NETWORK_ERROR":
            return ErrorCode.NETWORK_ERROR
        if code == "INVALID_JSON":
            return ErrorCode.INVALID_JSON
        if code == "MAX_PAGES_EXCEEDED":
            return ErrorCode.MAX_PAGES_EXCEEDED
        if code == "API_CONFLICT" or code == "HTTP_409":
            return ErrorCode.API_CONFLICT
        if code.startswith("HTTP_"):
            if status_code:
                if 400 <= status_code <= 499:
                    return ErrorCode.HTTP_4XX
                if 500 <= status_code <= 599:
                    return ErrorCode.HTTP_5XX
            return ErrorCode.HTTP_UNEXPECTED_STATUS
        return ErrorCode.UNKNOWN_ERROR
