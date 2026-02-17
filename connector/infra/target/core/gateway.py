"""
TargetGateway — единственный владелец retry-политики.

Назначение:
    Переводит потребности приложения в операции target, используя
    TargetKernel для классификации и TargetDriver для I/O.

Контракт:
    - Структурно удовлетворяет RequestExecutorProtocol (`execute`).
    - Структурно удовлетворяет TargetPagedReaderProtocol (`iter_pages`).
    - Retry только по директивам из spec.retry_rules.
    - Никогда не бросает исключений наружу (нормализует в результирующие объекты).
"""

from __future__ import annotations

import time
from typing import Any, Iterable

from connector.common.sanitize import maskSecretsInObject, truncateText
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.target.execution import ExecutionResult, RequestSpec
from connector.domain.ports.target.read import TargetPageResult
from connector.infra.target.core.engines import (
    NormalizedFault,
    TargetErrorNormalizer,
    TargetRetryEngine,
    TargetSafeLogger,
)
from connector.infra.target.core.kernel import ResolvedRetryAction, TargetKernel
from connector.infra.target.core.models import TargetCheckResult
from connector.infra.target.core.mutations import TargetMutationRegistry
from connector.infra.target.driver import DriverError, DriverResponse, TargetDriver


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
        driver: TargetDriver[Any],
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
        """Выполнить RequestSpec с retry по spec.retry_rules. Никогда не бросает."""
        try:
            self._kernel.require_capability("execute")
        except ValueError as exc:
            self._failures_total += 1
            return self._spec_error(str(exc))

        retries_used = 0
        current_spec = spec

        while True:
            try:
                _, compiled = self._kernel.get_compiled_operation(current_spec.operation_alias)
                compiled_request = compiled.build(
                    alias=current_spec.operation_alias,
                    operation_params=current_spec.operation_params,
                )
            except ValueError as exc:
                self._failures_total += 1
                return self._spec_error(str(exc))
            except Exception as exc:
                self._failures_total += 1
                return self._unexpected_failure(exc)

            self._requests_total += 1

            try:
                resp = self._driver.execute(compiled_request, current_spec.payload)
            except DriverError as exc:
                normalized, retry_action = self._resolve_driver_error(exc)
                try:
                    should_retry, retries_used, current_spec = self._apply_retry_action(
                        operation="execute",
                        fault_kind=normalized.fault_kind,
                        retry_action=retry_action,
                        retries_used=retries_used,
                        current_spec=current_spec,
                        retry_after_s=exc.retry_after_s,
                    )
                except ValueError as mutation_error:
                    self._failures_total += 1
                    return self._spec_error(str(mutation_error))
                if should_retry:
                    continue

                self._failures_total += 1
                error_details = self._driver_error_details(exc)
                if retry_action.directive == "ESCALATE":
                    error_details = self._mark_escalated(error_details)
                return ExecutionResult(
                    ok=False,
                    answer_code=exc.answer_code,
                    response_payload=None,
                    error_code=normalized.error_code,
                    error_message=truncateText(str(exc)),
                    error_reason=exc.error_reason,
                    error_details=error_details,
                )
            except Exception as exc:
                self._failures_total += 1
                return self._unexpected_failure(exc)

            if resp.ok:
                safe_payload = self._sanitize(resp.payload)
                return ExecutionResult(
                    ok=True,
                    answer_code=resp.answer_code,
                    response_payload=safe_payload,
                    response_format=resp.payload_format,
                )

            normalized, retry_action = self._resolve_driver_response(resp)
            try:
                should_retry, retries_used, current_spec = self._apply_retry_action(
                    operation="execute",
                    fault_kind=normalized.fault_kind,
                    retry_action=retry_action,
                    retries_used=retries_used,
                    current_spec=current_spec,
                    retry_after_s=resp.retry_after_s,
                )
            except ValueError as mutation_error:
                self._failures_total += 1
                return self._spec_error(str(mutation_error))
            if should_retry:
                continue

            self._failures_total += 1
            details = self._safe_logger.build_error_details(
                payload=resp.payload,
                content_preview=resp.content_preview,
            )
            if resp.error_reason is not None:
                details = dict(details or {})
                details["error_reason"] = resp.error_reason
            if retry_action.directive == "ESCALATE":
                details = self._mark_escalated(details)
            safe_payload = details.get("response_payload") if isinstance(details, dict) else None

            return ExecutionResult(
                ok=False,
                answer_code=resp.answer_code,
                response_payload=safe_payload,
                response_format=resp.payload_format if safe_payload is not None else "none",
                error_code=normalized.error_code,
                error_message=self._format_answer_failure(resp.answer_code),
                error_reason=resp.error_reason,
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
        """Чтение страниц из target. Нормализует ошибки в TargetPageResult."""
        try:
            self._kernel.require_capability("read_paged")
            _, compiled = self._kernel.get_compiled_operation(operation_alias)
            compiled_request = compiled.build(
                alias=operation_alias,
                query_overrides=params,
            )
        except ValueError as exc:
            self._failures_total += 1
            yield TargetPageResult(
                ok=False,
                page=0,
                items=None,
                error_code=self._kernel.system_error_code("SPEC"),
                error_message=truncateText(str(exc)),
            )
            return
        except Exception as exc:
            self._failures_total += 1
            yield TargetPageResult(
                ok=False,
                page=0,
                items=None,
                error_code=SystemErrorCode.INFRA_UNAVAILABLE,
                error_message=truncateText(str(exc)),
            )
            return

        retries_used = 0
        last_page = 0

        while True:
            try:
                for page, items in self._driver.iter_batches(
                    compiled_request,
                    page_size,
                    max_pages,
                ):
                    self._requests_total += 1
                    last_page = page
                    safe_items = maskSecretsInObject(items)
                    yield TargetPageResult(ok=True, page=page, items=safe_items)
                return
            except DriverError as exc:
                normalized, retry_action = self._resolve_driver_error(exc)
                # Если страницы уже начали выдавать — не ретраим, чтобы не дублировать данные.
                if last_page == 0:
                    try:
                        should_retry, retries_used, _ = self._apply_retry_action(
                            operation="read",
                            fault_kind=normalized.fault_kind,
                            retry_action=retry_action,
                            retries_used=retries_used,
                            current_spec=None,
                            retry_after_s=exc.retry_after_s,
                        )
                    except ValueError as mutation_error:
                        self._failures_total += 1
                        yield TargetPageResult(
                            ok=False,
                            page=last_page,
                            items=None,
                            error_code=self._kernel.system_error_code("SPEC"),
                            error_message=truncateText(str(mutation_error)),
                        )
                        return
                    if should_retry:
                        continue

                self._failures_total += 1
                error_details = self._driver_error_details(exc)
                if retry_action.directive == "ESCALATE":
                    error_details = self._mark_escalated(error_details)
                yield TargetPageResult(
                    ok=False,
                    page=last_page,
                    items=None,
                    error_code=normalized.error_code,
                    error_message=truncateText(str(exc)),
                    error_details=error_details or None,
                )
                return
            except Exception as exc:
                self._failures_total += 1
                yield TargetPageResult(
                    ok=False,
                    page=last_page,
                    items=None,
                    error_code=SystemErrorCode.INFRA_UNAVAILABLE,
                    error_message=truncateText(str(exc)),
                )
                return

    # ------------------------------------------------------------------
    # Проверка доступности
    # ------------------------------------------------------------------

    def health_check(self) -> TargetCheckResult:
        """Выполнить health-check через operation alias из TargetSpec.health."""
        try:
            self._kernel.require_capability("check")
            operation_alias = self._kernel.health_operation_alias()
            _, compiled = self._kernel.get_compiled_operation(operation_alias)
            compiled_request = compiled.build(alias=operation_alias)
        except ValueError as exc:
            return TargetCheckResult(
                ok=False,
                fault_kind="SPEC",
                error_code=self._kernel.system_error_code("SPEC"),
                error_message=truncateText(str(exc)),
            )

        start = time.monotonic()
        try:
            resp = self._driver.execute(compiled_request, None)
            latency_ms = int((time.monotonic() - start) * 1000)
            if resp.ok:
                return TargetCheckResult(ok=True, latency_ms=latency_ms)
            normalized = self._error_normalizer.from_status(self._as_status_code(resp.answer_code))
            return TargetCheckResult(
                ok=False,
                latency_ms=latency_ms,
                fault_kind=normalized.fault_kind,
                error_code=normalized.error_code,
                error_message=self._format_answer_failure(resp.answer_code),
            )
        except DriverError as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            normalized = self._error_normalizer.from_status_or_code(
                status_code=self._as_status_code(exc.answer_code),
                error_code=exc.code,
            )
            return TargetCheckResult(
                ok=False,
                latency_ms=latency_ms,
                fault_kind=normalized.fault_kind,
                error_code=normalized.error_code,
                error_message=truncateText(str(exc)),
            )
        except Exception as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            return TargetCheckResult(
                ok=False,
                latency_ms=latency_ms,
                fault_kind="TRANSIENT",
                error_code=SystemErrorCode.INFRA_UNAVAILABLE,
                error_message=truncateText(str(exc)),
            )

    # ------------------------------------------------------------------
    # Счётчики
    # ------------------------------------------------------------------

    def get_stats(self) -> tuple[int, int, int]:
        """Вернуть `(requests_total, retries_total, failures_total)`.

        requests_total считает execute-попытки и успешно выданные read-страницы.
        """
        return (self._requests_total, self._retries_total, self._failures_total)

    def reset_stats(self) -> None:
        self._requests_total = 0
        self._retries_total = 0
        self._failures_total = 0

    def close(self) -> None:
        self._driver.close()

    # ------------------------------------------------------------------
    # Внутренние вспомогательные методы
    # ------------------------------------------------------------------

    def _sanitize(self, payload: Any) -> Any:
        return self._safe_logger.safe_body(payload)

    def _apply_retry_action(
        self,
        *,
        operation: str,
        fault_kind: str,
        retry_action: ResolvedRetryAction,
        retries_used: int,
        current_spec: RequestSpec | None,
        retry_after_s: float | None = None,
    ) -> tuple[bool, int, RequestSpec | None]:
        directive = retry_action.directive
        if directive not in {"RETRY_BACKOFF", "RETRY_AFTER"}:
            return False, retries_used, current_spec
        if not self._retry_engine.can_retry(retries_used):
            return False, retries_used, current_spec

        if retry_action.mutation is not None:
            if current_spec is None:
                raise ValueError(
                    f"retry mutation {retry_action.mutation!r} cannot be applied without request spec",
                )
            current_spec = self._mutations.apply(retry_action.mutation, current_spec)

        retries_used += 1
        self._retries_total += 1
        if directive == "RETRY_AFTER" and retry_after_s is not None:
            delay = self._retry_engine.sleep_exact(retry_after_s)
        else:
            delay = self._retry_engine.sleep_before_retry(retries_used)
        self._safe_logger.debug_retry(
            operation=operation,
            fault_kind=fault_kind,
            retries_used=retries_used,
            max_retries=self._retry_engine.max_retries,
            delay_s=delay,
            mutation=retry_action.mutation,
        )
        return True, retries_used, current_spec

    def _driver_error_details(self, exc: DriverError) -> dict[str, Any] | None:
        error_details: dict[str, Any] | None = None
        if isinstance(exc.details, dict) and exc.details:
            safe_details = self._safe_logger.safe_body(exc.details)
            error_details = safe_details if isinstance(safe_details, dict) else None
        content_preview = exc.content_preview or (
            error_details.get("content_preview")
            if isinstance(error_details, dict)
            else None
        )
        if content_preview is not None:
            error_details = dict(error_details or {})
            truncated = truncateText(str(content_preview))
            error_details["content_preview"] = truncated
        if exc.error_reason is not None:
            error_details = dict(error_details or {})
            error_details["error_reason"] = exc.error_reason
        return error_details

    def _resolve_driver_error(
        self,
        exc: DriverError,
    ) -> tuple[NormalizedFault, ResolvedRetryAction]:
        status_code = self._as_status_code(exc.answer_code)
        normalized = self._error_normalizer.from_status_or_code(
            status_code=status_code,
            error_code=exc.code,
        )
        retry_action = self._kernel.resolve_retry_action(
            fault_kind=normalized.fault_kind,
            status_code=status_code,
            error_reason=exc.error_reason,
        )
        return normalized, retry_action

    def _resolve_driver_response(
        self,
        resp: DriverResponse,
    ) -> tuple[NormalizedFault, ResolvedRetryAction]:
        status_code = self._as_status_code(resp.answer_code)
        normalized = self._error_normalizer.from_status(status_code)
        retry_action = self._kernel.resolve_retry_action(
            fault_kind=normalized.fault_kind,
            status_code=status_code,
            error_reason=resp.error_reason,
        )
        return normalized, retry_action

    @staticmethod
    def _mark_escalated(details: dict[str, Any] | None) -> dict[str, Any]:
        payload = dict(details or {})
        payload["escalated"] = True
        return payload

    @staticmethod
    def _as_status_code(answer_code: int | str | None) -> int | None:
        if type(answer_code) is int:
            return answer_code
        return None

    @staticmethod
    def _format_answer_failure(answer_code: int | str | None) -> str:
        if answer_code is None:
            return "target operation failed"
        return f"target answer {answer_code}"

    def _unexpected_failure(self, exc: Exception) -> ExecutionResult:
        return ExecutionResult(
            ok=False,
            answer_code=None,
            response_payload=None,
            error_code=SystemErrorCode.INFRA_UNAVAILABLE,
            error_message=truncateText(str(exc)),
        )

    def _spec_error(self, message: str) -> ExecutionResult:
        return ExecutionResult(
            ok=False,
            answer_code=None,
            response_payload=None,
            error_code=self._kernel.system_error_code("SPEC"),
            error_message=truncateText(message),
        )
