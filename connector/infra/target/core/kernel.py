"""
TargetKernel — валидация spec, классификация ошибок, retry-директивы, redaction.

Назначение:
    Предоставляет O(1) доступ для классификации ошибок и retry-директив
    на основе правил из TargetSpec. Единая точка для redaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connector.common.sanitize import maskSecretsInObject
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.target.core.models import TargetFaultKind
from connector.infra.target.core.spec_models import (
    OperationSpec,
    RedactionSpec,
    RetryDirective,
    RetryRule,
    TargetSpec,
)
from connector.infra.target.core.transport_compiler import (
    CompiledOperation,
    TransportCompilerRegistry,
)

# ---------------------------------------------------------------------------
# Табличный маппинг: FaultKind → SystemErrorCode
# Согласовано с существующим `map_http_status` из `policies.py`.
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


@dataclass(frozen=True, slots=True)
class ResolvedHttpOperation:
    """Скомпилированный HTTP-запрос из alias OperationSpec."""

    method: str
    path: str
    query: dict[str, Any]
    headers: dict[str, str]
    expected_statuses: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ResolvedRetryAction:
    """Решение о retry для текущей ошибки."""

    directive: RetryDirective
    mutation: str | None = None


class TargetKernel:
    """
    Назначение:
        Валидирует/нормализует TargetSpec и предоставляет операции:
        classify_fault, retry_directive, system_error_code, redaction.

    Контракт:
        - Lookup-таблицы собираются при инициализации для O(1) доступа.
        - Компиляция операций делегируется в TransportCompilerRegistry.
        - `classify_fault`: `error_code` имеет приоритет над `status_code`.
        - `retry_directive`: если правило не найдено — `NO_RETRY`.
    """

    def __init__(
        self,
        spec: TargetSpec,
        compiler_registry: TransportCompilerRegistry,
    ) -> None:
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
        self._retry_rules: tuple[RetryRule, ...] = spec.retry_rules
        self._operations: dict[str, OperationSpec] = {}
        self._compiled_operations: dict[str, CompiledOperation] = {}
        for key, operation in spec.operations.items():
            if key != operation.alias:
                raise ValueError(
                    f"operation alias key mismatch: key={key!r}, alias={operation.alias!r}",
                )
            self._compiled_operations[key] = compiler_registry.compile(operation)
            self._operations[key] = operation

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
        `error_code` имеет приоритет (например, NETWORK_ERROR при `status_code=None`).
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

    def resolve_retry_action(
        self,
        *,
        fault_kind: TargetFaultKind,
        status_code: int | None = None,
        error_reason: str | None = None,
    ) -> ResolvedRetryAction:
        """
        Разрешить retry-директиву и мутацию по правилам spec.

        Правила применяются в декларативном порядке (`spec.retry_rules`).
        """
        normalized_reason = error_reason.strip().lower() if isinstance(error_reason, str) else None
        for rule in self._retry_rules:
            if rule.match_fault is not None and rule.match_fault != fault_kind:
                continue
            if rule.match_status is not None and rule.match_status != status_code:
                continue
            if rule.match_reason is not None and rule.match_reason != normalized_reason:
                continue
            return ResolvedRetryAction(
                directive=rule.directive,
                mutation=rule.mutation,
            )
        return ResolvedRetryAction(directive="NO_RETRY", mutation=None)

    def retry_directive(self, fault_kind: TargetFaultKind) -> RetryDirective:
        """Определить retry-директиву по fault-kind (совместимый API)."""
        return self.resolve_retry_action(fault_kind=fault_kind).directive

    def resolve_operation(self, alias: str) -> OperationSpec:
        """Разрешить alias в декларацию операции."""
        operation = self._operations.get(alias)
        if operation is None:
            raise ValueError(f"unknown operation alias: {alias}")
        return operation

    def build_http_operation(
        self,
        alias: str,
        *,
        operation_params: dict[str, Any] | None = None,
        query_overrides: dict[str, Any] | None = None,
        header_overrides: dict[str, str] | None = None,
    ) -> ResolvedHttpOperation:
        """
        Построить HTTP-запрос строго из OperationSpec.
        `method/path/expected_statuses` берутся только из alias-каталога.
        """
        operation = self.resolve_operation(alias)
        if operation.kind != "http":
            raise ValueError(f"operation {alias!r} is not http")
        compiled = self._compiled_operations.get(alias)
        if compiled is None:
            raise ValueError(f"operation {alias!r} is not compiled")

        request = compiled.build(
            alias=alias,
            operation_params=operation_params,
            query_overrides=query_overrides,
            header_overrides=header_overrides,
        )
        method = getattr(request, "method", None)
        path = getattr(request, "path", None)
        query = getattr(request, "query", None)
        headers = getattr(request, "headers", None)
        if not isinstance(method, str) or not isinstance(path, str):
            raise ValueError(f"operation {alias!r} produced invalid request payload")
        if query is None:
            query = {}
        if headers is None:
            headers = {}
        return ResolvedHttpOperation(
            method=method,
            path=path,
            query=dict(query),
            headers=dict(headers),
            expected_statuses=operation.expected_statuses,
        )

    def system_error_code(self, fault_kind: TargetFaultKind) -> SystemErrorCode:
        """Перевести FaultKind в SystemErrorCode для диагностик."""
        return _FAULT_TO_SYSTEM.get(fault_kind, SystemErrorCode.INTERNAL_ERROR)

    def redact_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Замаскировать запрещённые заголовки для безопасного логирования."""
        forbidden = self._spec.redaction.forbidden_headers
        return {
            k: ("***" if k.lower() in forbidden else v) for k, v in headers.items()
        }

    def redact_payload(self, payload: Any) -> Any:
        """Замаскировать секретные поля в payload-данных."""
        return maskSecretsInObject(payload)

    def safe_body(self, body: Any, redaction: RedactionSpec | None = None) -> Any:
        """Вернуть безопасное представление тела ответа в зависимости от `body_mode`."""
        mode = (redaction or self._spec.redaction).body_mode
        if mode == "none":
            return None
        if mode == "keys_only" and isinstance(body, dict):
            return list(body.keys())
        return maskSecretsInObject(body)
