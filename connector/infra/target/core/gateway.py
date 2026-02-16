"""
TargetGateway — единственный владелец retry-политики.

Назначение:
    Переводит потребности приложения в операции target, используя
    TargetKernel для классификации и TargetDriver для I/O.

Контракт:
    - Структурно удовлетворяет RequestExecutorProtocol (`execute`).
    - Структурно удовлетворяет TargetPagedReaderProtocol (`iter_pages`).
    - Retry только для RETRY_BACKOFF / RETRY_AFTER по fault_rules.
    - Никогда не бросает исключений наружу (нормализует в результирующие объекты).
"""

from __future__ import annotations

import time
from typing import Any, Iterable

from connector.common.sanitize import maskSecretsInObject, truncateText
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.target.execution import ExecutionResult, RequestSpec
from connector.domain.ports.target.read import TargetPageResult
from connector.infra.http.ankey_client import ApiError
from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.core.mutations import TargetMutationRegistry
from connector.infra.target.core.engines import (
    TargetErrorNormalizer,
    TargetRetryEngine,
    TargetSafeLogger,
)
from connector.infra.target.core.models import TargetCheckResult
from connector.infra.target.driver import DriverError, TargetDriver


class TargetGateway:
    """
    Назначение:
        Единственный владелец retry-политики для target-операций.

    Взаимодействия:
        - TargetDriver: I/O с одной попыткой.
        - TargetKernel: `classify_fault` → `retry_directive` → `system_error_code`.
    """

    def __init__(
        self,
        driver: TargetDriver,
        kernel: TargetKernel,
        *,
        mutation_registry: TargetMutationRegistry | None = None,
    ) -> None:
        self._driver = driver
        self._kernel = kernel
        self._mutations = mutation_registry or TargetMutationRegistry()
        self._retry_engine = TargetRetryEngine(kernel.spec.retry_config)
        self._error_normalizer = TargetErrorNormalizer(kernel)
        self._safe_logger = TargetSafeLogger(kernel, logger_name=__name__)
        self._requests_total: int = 0
        self._retries_total: int = 0
        self._failures_total: int = 0

    # ------------------------------------------------------------------
    # Реализация RequestExecutorProtocol
    # ------------------------------------------------------------------

    def execute(self, spec: RequestSpec) -> ExecutionResult:
        """
        Выполнить RequestSpec с retry по spec.retry_rules. Никогда не бросает.
        """
        retries_used = 0
        current_spec = spec

        while True:
            resolved = self._resolve_execute_request(current_spec)
            if isinstance(resolved, ExecutionResult):
                self._failures_total += 1
                return resolved

            method, path, params, headers, expected_statuses = resolved
            self._requests_total += 1

            try:
                resp = self._driver.request(
                    method,
                    path,
                    params=params,
                    json=current_spec.payload,
                    headers=headers,
                )
            except DriverError as exc:
                normalized = self._error_normalizer.from_error_code(exc.code)
                fault = normalized.fault_kind
                retry_action = self._kernel.resolve_retry_action(fault_kind=fault)
                if retry_action.directive == "RETRY_BACKOFF" and self._retry_engine.can_retry(retries_used):
                    if retry_action.mutation is not None:
                        try:
                            current_spec = self._mutations.apply(retry_action.mutation, current_spec)
                        except ValueError as mutation_error:
                            self._failures_total += 1
                            return self._spec_error(str(mutation_error))
                    retries_used += 1
                    self._retries_total += 1
                    delay = self._retry_engine.sleep_before_retry(retries_used)
                    self._safe_logger.debug_retry(
                        operation="execute",
                        fault_kind=fault,
                        retries_used=retries_used,
                        max_retries=self._retry_engine.max_retries,
                        delay_s=delay,
                        mutation=retry_action.mutation,
                    )
                    continue
                self._failures_total += 1
                return ExecutionResult(
                    ok=False,
                    status_code=None,
                    response_json=None,
                    error_code=normalized.error_code,
                    error_message=truncateText(str(exc)),
                )

            if resp.status_code in expected_statuses:
                safe_body = self._sanitize(resp.body)
                safe_json = safe_body if isinstance(safe_body, (dict, list)) else None
                return ExecutionResult(
                    ok=True,
                    status_code=resp.status_code,
                    response_json=safe_json,
                )

            normalized = self._error_normalizer.from_status(resp.status_code)
            fault = normalized.fault_kind
            reason = self._detect_error_reason(resp.body, resp.body_snippet)
            retry_action = self._kernel.resolve_retry_action(
                fault_kind=fault,
                status_code=resp.status_code,
                error_reason=reason,
            )
            if retry_action.directive == "RETRY_BACKOFF" and self._retry_engine.can_retry(retries_used):
                if retry_action.mutation is not None:
                    try:
                        current_spec = self._mutations.apply(retry_action.mutation, current_spec)
                    except ValueError as mutation_error:
                        self._failures_total += 1
                        return self._spec_error(str(mutation_error))
                retries_used += 1
                self._retries_total += 1
                delay = self._retry_engine.sleep_before_retry(retries_used)
                self._safe_logger.debug_retry(
                    operation="execute",
                    fault_kind=fault,
                    retries_used=retries_used,
                    max_retries=self._retry_engine.max_retries,
                    delay_s=delay,
                    mutation=retry_action.mutation,
                )
                continue

            self._failures_total += 1
            details = self._safe_logger.build_error_details(
                body=resp.body,
                body_snippet=resp.body_snippet,
            )
            safe_json = details.get("response_json") if isinstance(details, dict) else None

            return ExecutionResult(
                ok=False,
                status_code=resp.status_code,
                response_json=safe_json,
                error_code=normalized.error_code,
                error_message=f"HTTP {resp.status_code}",
                error_reason=reason,
                error_details=details,
            )

    # ------------------------------------------------------------------
    # Реализация TargetPagedReaderProtocol
    # ------------------------------------------------------------------

    def iter_pages(
        self,
        operation_alias: str,
        page_size: int,
        max_pages: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterable[TargetPageResult]:
        """
        Чтение страниц из target. Нормализует ошибки в TargetPageResult.
        """
        resolved = self._resolve_read_operation(
            operation_alias,
            query_overrides=params,
        )
        if isinstance(resolved, TargetPageResult):
            self._failures_total += 1
            yield resolved
            return

        path, query = resolved
        retries_used = 0
        last_page = 0

        while True:
            try:
                for page, items in self._driver.get_paged_items(
                    path,
                    page_size,
                    max_pages,
                    params=query,
                ):
                    self._requests_total += 1
                    last_page = page
                    safe_items = maskSecretsInObject(items)
                    yield TargetPageResult(ok=True, page=page, items=safe_items)
                return
            except DriverError as exc:
                normalized = self._error_normalizer.from_error_code(exc.code)
                fault = normalized.fault_kind
                directive = self._kernel.retry_directive(fault)
                # Если страницы уже начали выдавать — не ретраим, чтобы не дублировать данные.
                if (
                    last_page == 0
                    and directive == "RETRY_BACKOFF"
                    and self._retry_engine.can_retry(retries_used)
                ):
                    retries_used += 1
                    self._retries_total += 1
                    delay = self._retry_engine.sleep_before_retry(retries_used)
                    self._safe_logger.debug_retry(
                        operation="read",
                        fault_kind=fault,
                        retries_used=retries_used,
                        max_retries=self._retry_engine.max_retries,
                        delay_s=delay,
                    )
                    continue

                self._failures_total += 1
                yield TargetPageResult(
                    ok=False,
                    page=last_page,
                    items=None,
                    error_code=normalized.error_code,
                    error_message=str(exc),
                )
                return
            except ApiError as exc:
                normalized = self._error_normalizer.from_status_or_code(
                    status_code=exc.status_code, error_code=exc.code,
                )
                fault = normalized.fault_kind
                directive = self._kernel.retry_directive(fault)
                # Если страницы уже начали выдавать — не ретраим, чтобы не дублировать данные.
                if (
                    last_page == 0
                    and directive == "RETRY_BACKOFF"
                    and self._retry_engine.can_retry(retries_used)
                ):
                    retries_used += 1
                    self._retries_total += 1
                    delay = self._retry_engine.sleep_before_retry(retries_used)
                    self._safe_logger.debug_retry(
                        operation="read",
                        fault_kind=fault,
                        retries_used=retries_used,
                        max_retries=self._retry_engine.max_retries,
                        delay_s=delay,
                    )
                    continue

                self._failures_total += 1
                error_details: dict[str, Any] | None = None
                if isinstance(exc.details, dict):
                    safe_details = self._safe_logger.safe_body(exc.details)
                    error_details = safe_details if isinstance(safe_details, dict) else None
                body_snippet = exc.body_snippet or (
                    error_details.get("body_snippet")
                    if isinstance(error_details, dict)
                    else None
                )
                if body_snippet is not None:
                    error_details = dict(error_details or {})
                    error_details["body_snippet"] = truncateText(str(body_snippet))

                yield TargetPageResult(
                    ok=False,
                    page=last_page,
                    items=None,
                    error_code=normalized.error_code,
                    error_message=truncateText(str(exc)),
                    error_details=error_details or None,
                )
                return

    # ------------------------------------------------------------------
    # Проверка доступности
    # ------------------------------------------------------------------

    def health_check(self) -> TargetCheckResult:
        """Выполнить health-check через operation alias `health.check`."""
        resolved = self._resolve_health_operation()
        if isinstance(resolved, TargetCheckResult):
            return resolved
        method, path, query, headers, expected_statuses = resolved
        start = time.monotonic()
        try:
            response = self._driver.request(
                method,
                path,
                params=query,
                headers=headers,
            )
            latency_ms = int((time.monotonic() - start) * 1000)
            if response.status_code in expected_statuses:
                return TargetCheckResult(ok=True, latency_ms=latency_ms)
            normalized = self._error_normalizer.from_status(response.status_code)
            return TargetCheckResult(
                ok=False,
                latency_ms=latency_ms,
                fault_kind=normalized.fault_kind,
                error_code=normalized.error_code,
                error_message=f"HTTP {response.status_code}",
            )
        except DriverError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            normalized = self._error_normalizer.from_error_code(exc.code)
            return TargetCheckResult(
                ok=False,
                latency_ms=latency_ms,
                fault_kind=normalized.fault_kind,
                error_code=normalized.error_code,
                error_message=str(exc),
            )
        except ApiError as exc:  # pragma: no cover - защитный путь
            latency_ms = int((time.monotonic() - start) * 1000)
            normalized = self._error_normalizer.from_status_or_code(
                status_code=exc.status_code,
                error_code=exc.code,
            )
            return TargetCheckResult(
                ok=False,
                latency_ms=latency_ms,
                fault_kind=normalized.fault_kind,
                error_code=normalized.error_code,
                error_message=str(exc),
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            return TargetCheckResult(
                ok=False,
                latency_ms=latency_ms,
                fault_kind="TRANSIENT",
                error_code=SystemErrorCode.INFRA_UNAVAILABLE,
                error_message=str(exc),
            )

    # ------------------------------------------------------------------
    # Счётчики
    # ------------------------------------------------------------------

    def get_stats(self) -> tuple[int, int, int]:
        """Вернуть `(requests_total, retries_total, failures_total)`."""
        return (self._requests_total, self._retries_total, self._failures_total)

    def reset_stats(self) -> None:
        self._requests_total = 0
        self._retries_total = 0
        self._failures_total = 0

    # ------------------------------------------------------------------
    # Внутренние вспомогательные методы
    # ------------------------------------------------------------------

    def _sanitize(self, payload: Any) -> Any:
        safe = self._safe_logger.safe_body(payload)
        if isinstance(safe, str):
            return truncateText(safe)
        return safe

    @staticmethod
    def _detect_error_reason(payload: Any, body_snippet: str | None) -> str | None:
        """
        Выделить семантическую причину ошибки (например 'resourceexists').
        Перенесено из AnkeyRequestExecutor._detect_error_reason.
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

    def _resolve_execute_request(
        self,
        spec: RequestSpec,
    ) -> tuple[str, str, dict[str, Any] | None, dict[str, str] | None, tuple[int, ...]] | ExecutionResult:
        if spec.operation_alias:
            try:
                operation = self._kernel.build_http_operation(
                    spec.operation_alias,
                    operation_params=spec.operation_params,
                    query_overrides=spec.query,
                    header_overrides=spec.headers,
                )
            except ValueError as exc:
                return self._spec_error(str(exc))
            return (
                operation.method,
                operation.path,
                operation.query or None,
                operation.headers or None,
                operation.expected_statuses,
            )

        if spec.method is None or spec.path is None:
            return self._spec_error("request spec must include method/path or operation_alias")
        return (
            spec.method,
            spec.path,
            spec.query,
            spec.headers,
            tuple(spec.expected_statuses),
        )

    def _spec_error(self, message: str) -> ExecutionResult:
        return ExecutionResult(
            ok=False,
            status_code=None,
            response_json=None,
            error_code=self._kernel.system_error_code("SPEC"),
            error_message=truncateText(message),
        )

    def _resolve_read_operation(
        self,
        operation_alias: str,
        *,
        query_overrides: dict[str, Any] | None = None,
    ) -> tuple[str, dict[str, Any] | None] | TargetPageResult:
        try:
            operation = self._kernel.build_http_operation(
                operation_alias,
                query_overrides=query_overrides,
            )
        except ValueError as exc:
            return TargetPageResult(
                ok=False,
                page=0,
                items=None,
                error_code=self._kernel.system_error_code("SPEC"),
                error_message=truncateText(str(exc)),
            )
        if operation.method != "GET":
            return TargetPageResult(
                ok=False,
                page=0,
                items=None,
                error_code=self._kernel.system_error_code("SPEC"),
                error_message=f"operation {operation_alias!r} must use GET for read_pages",
            )
        return operation.path, (operation.query or None)

    def _resolve_health_operation(
        self,
    ) -> tuple[str, str, dict[str, Any] | None, dict[str, str] | None, tuple[int, ...]] | TargetCheckResult:
        try:
            operation = self._kernel.build_http_operation("health.check")
        except ValueError as exc:
            return TargetCheckResult(
                ok=False,
                fault_kind="SPEC",
                error_code=self._kernel.system_error_code("SPEC"),
                error_message=truncateText(str(exc)),
            )
        return (
            operation.method,
            operation.path,
            operation.query or None,
            operation.headers or None,
            operation.expected_statuses,
        )
