from __future__ import annotations

from typing import Any

from connector.common.sanitize import maskSecretsInObject, truncateText
from connector.domain.error_codes import ErrorCode
from connector.domain.ports.execution import ExecutionResult, RequestExecutorProtocol, RequestSpec
from connector.infra.http.ankey_client import ApiError, AnkeyApiClient


class AnkeyRequestExecutor(RequestExecutorProtocol):
    """
    Назначение:
        Адаптер порта RequestExecutorProtocol к AnkeyApiClient.
    """

    def __init__(self, client: AnkeyApiClient):
        self.client = client

    def execute(self, spec: RequestSpec) -> ExecutionResult:
        """
        Назначение:
            Выполнить RequestSpec и вернуть нормализованный ExecutionResult без исключений.
        """
        try:
            status_code, resp, body_snippet = self.client.requestAny(
                method=spec.method,
                path=spec.path,
                params=spec.query,
                jsonBody=spec.payload,
                headers=spec.headers,
            )
            ok = spec.is_expected(status_code)
            safe_body = self._sanitize(resp)
            safe_json = safe_body if isinstance(safe_body, (dict, list)) else None
            safe_snippet = truncateText(body_snippet) if body_snippet else None
            reason = self._detect_error_reason(resp, body_snippet)
            if ok:
                return ExecutionResult(
                    ok=True,
                    status_code=status_code,
                    response_json=safe_json,
                    error_reason=None,
                    error_details=None,
                )
            details: dict[str, Any] | None = None
            if safe_snippet or safe_json is not None:
                details = {}
                if safe_snippet:
                    details["body_snippet"] = safe_snippet
                if safe_json is not None:
                    details["response_json"] = safe_json
            return ExecutionResult(
                ok=False,
                status_code=status_code,
                response_json=safe_json,
                error_code=ErrorCode.from_status(status_code),
                error_message=f"HTTP {status_code}",
                error_reason=reason,
                error_details=details,
            )
        except ApiError as exc:
            safe_msg = truncateText(str(exc))
            safe_snippet = truncateText(exc.body_snippet) if exc.body_snippet else None
            reason = self._detect_error_reason(safe_snippet, exc.body_snippet)
            return ExecutionResult(
                ok=False,
                status_code=exc.status_code,
                response_json=None,
                error_code=self._error_from_api_error(exc),
                error_message=safe_msg,
                error_reason=reason,
                error_details={"body_snippet": safe_snippet} if safe_snippet else None,
            )
        except Exception as exc:
            return ExecutionResult(
                ok=False,
                status_code=None,
                response_json=None,
                error_code=ErrorCode.UNEXPECTED_ERROR,
                error_message=truncateText(str(exc)),
                error_reason=None,
                error_details=None,
            )

    def _sanitize(self, payload: Any) -> Any:
        """
        Назначение:
            Маскировать секреты и усекать длинные строки в ответах.
        """
        if isinstance(payload, str):
            return truncateText(payload)
        return maskSecretsInObject(payload)

    def _error_from_api_error(self, exc: ApiError) -> ErrorCode:
        """
        Назначение:
            Перевести ApiError в общий ErrorCode.
        """
        if exc.code == "INVALID_JSON":
            return ErrorCode.INVALID_JSON
        if exc.code == "NETWORK_ERROR":
            return ErrorCode.NETWORK_ERROR
        if exc.status_code:
            return ErrorCode.from_status(exc.status_code)
        return ErrorCode.API_ERROR

    def _detect_error_reason(self, payload: Any, body_snippet: str | None) -> str | None:
        """
        Назначение:
            Выделить семантическую причину ошибки из ответа/snippet.
        """
        haystacks: list[str] = []
        if isinstance(payload, str):
            haystacks.append(payload)
        if isinstance(payload, dict):
            haystacks.extend(str(v) for v in payload.values())
        if body_snippet:
            haystacks.append(body_snippet)
        joined = " ".join(haystacks).lower()
        if "resourceexists" in joined or "resource exists" in joined:
            return "resourceexists"
        return None
