"""
TargetKernel — валидация spec, классификация ошибок, retry-директивы, redaction.

Назначение:
    Предоставляет O(1) lookup для fault classification и retry directive
    на основе правил из TargetSpec. Единая точка для redaction.
"""

from __future__ import annotations

from typing import Any

from connector.common.sanitize import maskSecretsInObject
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.target.models import TargetFaultKind
from connector.infra.target.spec import RedactionSpec, RetryDirective, TargetSpec

# ---------------------------------------------------------------------------
# Table-driven mapping: FaultKind → SystemErrorCode
# Согласовано с существующим map_http_status из policies.py
# ---------------------------------------------------------------------------
_FAULT_TO_SYSTEM: dict[TargetFaultKind, SystemErrorCode] = {
    "AUTH": SystemErrorCode.AUTH_UNAUTHORIZED,
    "PERMISSION": SystemErrorCode.AUTH_FORBIDDEN,
    "DATA": SystemErrorCode.DATA_INVALID,
    "NOT_FOUND": SystemErrorCode.DATA_INVALID,
    "CONFLICT": SystemErrorCode.CONFLICT,
    "THROTTLE": SystemErrorCode.INFRA_UNAVAILABLE,
    "TRANSIENT": SystemErrorCode.INFRA_UNAVAILABLE,
    "SPEC": SystemErrorCode.INTERNAL_ERROR,
    "UNKNOWN": SystemErrorCode.INTERNAL_ERROR,
}


class TargetKernel:
    """
    Назначение:
        Валидирует/нормализует TargetSpec и предоставляет операции:
        classify_fault, retry_directive, system_error_code, redaction.

    Контракт:
        - Pre-build lookup tables при инициализации для O(1) доступа.
        - classify_fault: error_code имеет приоритет над status_code.
        - retry_directive: если правило не найдено — NO_RETRY.
    """

    def __init__(self, spec: TargetSpec) -> None:
        self._spec = spec

        self._fault_by_status: dict[int, TargetFaultKind] = {
            r.match_status: r.fault_kind
            for r in spec.fault_rules
            if r.match_status is not None
        }
        self._fault_by_range: list[tuple[int, int, TargetFaultKind]] = [
            (*r.match_status_range, r.fault_kind)
            for r in spec.fault_rules
            if r.match_status_range is not None
        ]
        self._fault_by_code: dict[str, TargetFaultKind] = {
            r.match_error_code: r.fault_kind
            for r in spec.fault_rules
            if r.match_error_code is not None
        }
        self._retry_by_fault: dict[TargetFaultKind, RetryDirective] = {
            r.match_fault: r.directive
            for r in spec.retry_rules
            if r.match_fault is not None
        }

    @property
    def spec(self) -> TargetSpec:
        return self._spec

    def classify_fault(
        self,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
    ) -> TargetFaultKind:
        """
        Классифицировать ошибку по HTTP-статусу или коду ошибки драйвера.
        error_code имеет приоритет (например, NETWORK_ERROR при status_code=None).
        """
        if error_code and error_code in self._fault_by_code:
            return self._fault_by_code[error_code]

        if status_code is not None:
            if status_code in self._fault_by_status:
                return self._fault_by_status[status_code]
            for low, high, kind in self._fault_by_range:
                if low <= status_code <= high:
                    return kind

        return "UNKNOWN"

    def retry_directive(self, fault_kind: TargetFaultKind) -> RetryDirective:
        """Определить retry-директиву для данного класса ошибки."""
        return self._retry_by_fault.get(fault_kind, "NO_RETRY")

    def system_error_code(self, fault_kind: TargetFaultKind) -> SystemErrorCode:
        """Перевести FaultKind в SystemErrorCode для диагностик."""
        return _FAULT_TO_SYSTEM.get(fault_kind, SystemErrorCode.INTERNAL_ERROR)

    def redact_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Замаскировать запрещённые заголовки для safe-логирования."""
        forbidden = self._spec.redaction.forbidden_headers
        return {
            k: ("***" if k.lower() in forbidden else v) for k, v in headers.items()
        }

    def redact_payload(self, payload: Any) -> Any:
        """Замаскировать секретные поля в payload."""
        return maskSecretsInObject(payload)

    def safe_body(self, body: Any, redaction: RedactionSpec | None = None) -> Any:
        """Вернуть safe view тела ответа в зависимости от body_mode."""
        mode = (redaction or self._spec.redaction).body_mode
        if mode == "none":
            return None
        if mode == "keys_only" and isinstance(body, dict):
            return list(body.keys())
        return maskSecretsInObject(body)
