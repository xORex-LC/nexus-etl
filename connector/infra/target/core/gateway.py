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
    TargetErrorNormalizer,
    TargetFaultHandler,
    TargetResultBuilder,
    TargetRetryEngine,
    TargetSafeLogger,
)
from connector.infra.target.core.kernel import ResolvedRetryAction, TargetKernel
from connector.infra.target.core.models import TargetCheckResult
from connector.infra.target.core.mutations import TargetMutationRegistry
from connector.infra.target.driver import DriverError, TargetDriver


class TargetGateway:
    """
    Назначение:
        Единственный владелец retry-политики для target-операций.

    Взаимодействия:
        - TargetDriver: I/O с одной попыткой.
        - TargetKernel: `classify_fault` → `retry_directive` → `system_error_code`.
        - TargetFaultHandler: классификация ошибок и сборка error_details.
        - TargetResultBuilder: конструктор ExecutionResult.
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
        safe_logger = TargetSafeLogger(kernel, logger_name=__name__)
        normalizer = TargetErrorNormalizer(kernel)
        self._safe_logger = safe_logger
        self._fault_handler = TargetFaultHandler(kernel, normalizer, safe_logger)
        self._result_builder = TargetResultBuilder(kernel, safe_logger)
        self._requests_total: int = 0
        self._retries_total: int = 0
        self._failures_total: int = 0

    # ------------------------------------------------------------------
    # Реализация RequestExecutorProtocol
    # ------------------------------------------------------------------

    def execute(self, spec: RequestSpec) -> ExecutionResult:
        """Выполнить RequestSpec с retry по spec.retry_rules. Никогда не бросает."""
        _OP = "execute"
        try:
            self._kernel.require_capability(_OP)
        except ValueError as exc:
            self._failures_total += 1
            return self._result_builder.spec_error(str(exc))

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
                return self._result_builder.spec_error(str(exc))
            except Exception as exc:
                self._failures_total += 1
                return self._result_builder.unexpected_failure(exc)

            self._requests_total += 1

            try:
                resp = self._driver.execute(compiled_request, current_spec.payload)
            except DriverError as exc:
                normalized, retry_action = self._fault_handler.from_driver_error(exc)
                retry_after_s: float | None = exc.retry_after_s
                # В Python переменная исключения из ``except as`` очищается после блока.
                # Сохраняем ссылку явно, чтобы использовать её в отложенном замыкании.
                captured = exc
                make_error = lambda: self._result_builder.from_driver_error(
                    captured, normalized, self._fault_handler.build_exc_details(captured, retry_action)
                )
            except Exception as exc:
                self._failures_total += 1
                return self._result_builder.unexpected_failure(exc)
            else:
                if resp.ok:
                    return self._result_builder.execute_success(resp)
                normalized, retry_action = self._fault_handler.from_driver_response(resp)
                retry_after_s = resp.retry_after_s
                make_error = lambda: self._result_builder.from_response_error(
                    resp, normalized, self._fault_handler.build_resp_details(resp, retry_action)
                )

            try:
                should_retry, retries_used, current_spec = self._apply_execute_retry(
                    operation=_OP,
                    fault_kind=normalized.fault_kind,
                    retry_action=retry_action,
                    retries_used=retries_used,
                    current_spec=current_spec,
                    retry_after_s=retry_after_s,
                )
            except ValueError as mutation_error:
                self._failures_total += 1
                return self._result_builder.spec_error(str(mutation_error))
            if should_retry:
                continue

            self._failures_total += 1
            return make_error()

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
        retries_used = 0
        last_page = 0

        def _fail_page(error_code: str, error_message: str, error_details=None) -> TargetPageResult:
            # Единая точка создания fail-страницы упрощает одинаковую обработку ошибок.
            return TargetPageResult(ok=False, page=last_page, items=None, error_code=error_code, error_message=error_message, error_details=error_details)

        try:
            self._kernel.require_capability("read_paged")
            _, compiled = self._kernel.get_compiled_operation(operation_alias)
            compiled_request = compiled.build(
                alias=operation_alias,
                query_overrides=params,
            )
        except ValueError as exc:
            self._failures_total += 1
            yield _fail_page(self._kernel.system_error_code("SPEC"), truncateText(str(exc)))
            return
        except Exception as exc:
            self._failures_total += 1
            yield _fail_page(SystemErrorCode.INFRA_UNAVAILABLE, truncateText(str(exc)))
            return

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
                normalized, retry_action = self._fault_handler.from_driver_error(exc)
                # Если страницы уже начали выдавать — не ретраим, чтобы не дублировать данные.
                if last_page == 0:
                    should_retry, retries_used = self._apply_read_retry(
                        operation="read",
                        fault_kind=normalized.fault_kind,
                        retry_action=retry_action,
                        retries_used=retries_used,
                        retry_after_s=exc.retry_after_s,
                    )
                    if should_retry:
                        continue

                self._failures_total += 1
                error_details = self._fault_handler.build_exc_details(exc, retry_action)
                yield _fail_page(normalized.error_code, truncateText(str(exc)), error_details)
                return
            except Exception as exc:
                self._failures_total += 1
                yield _fail_page(SystemErrorCode.INFRA_UNAVAILABLE, truncateText(str(exc)))
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
        resp = None
        driver_exc: DriverError | None = None
        unexpected_exc: Exception | None = None
        try:
            resp = self._driver.execute(compiled_request, None)
        except DriverError as exc:
            driver_exc = exc
        except Exception as exc:
            unexpected_exc = exc

        latency_ms = int((time.monotonic() - start) * 1000)

        def _fail(fault_kind: str, error_code: str, error_message: str) -> TargetCheckResult:
            return TargetCheckResult(ok=False, latency_ms=latency_ms, fault_kind=fault_kind, error_code=error_code, error_message=error_message)

        if driver_exc is not None:
            normalized, _ = self._fault_handler.from_driver_error(driver_exc)
            return _fail(normalized.fault_kind, normalized.error_code, truncateText(str(driver_exc)))
        if unexpected_exc is not None:
            return _fail("TRANSIENT", SystemErrorCode.INFRA_UNAVAILABLE, truncateText(str(unexpected_exc)))
        assert resp is not None
        if resp.ok:
            return TargetCheckResult(ok=True, latency_ms=latency_ms)
        normalized, _ = self._fault_handler.from_driver_response(resp)
        return _fail(normalized.fault_kind, normalized.error_code, TargetFaultHandler.format_answer_failure(resp.answer_code))

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

    def _apply_execute_retry(
        self,
        *,
        operation: str,
        fault_kind: str,
        retry_action: ResolvedRetryAction,
        retries_used: int,
        current_spec: RequestSpec,
        retry_after_s: float | None = None,
    ) -> tuple[bool, int, RequestSpec]:
        """Применить retry-решение для execute. Может поднять ValueError при мутации."""
        directive = retry_action.directive
        if directive not in {"RETRY_BACKOFF", "RETRY_AFTER"}:
            return False, retries_used, current_spec
        if not self._retry_engine.can_retry(retries_used):
            return False, retries_used, current_spec

        if retry_action.mutation is not None:
            current_spec = self._mutations.apply(retry_action.mutation, current_spec)

        retries_used += 1
        self._retries_total += 1
        delay = self._compute_retry_delay(directive, retry_after_s, retries_used)
        self._safe_logger.debug_retry(
            operation=operation,
            fault_kind=fault_kind,
            retries_used=retries_used,
            max_retries=self._retry_engine.max_retries,
            delay_s=delay,
            mutation=retry_action.mutation,
        )
        return True, retries_used, current_spec

    def _apply_read_retry(
        self,
        *,
        operation: str,
        fault_kind: str,
        retry_action: ResolvedRetryAction,
        retries_used: int,
        retry_after_s: float | None = None,
    ) -> tuple[bool, int]:
        """Применить retry-решение для read. Мутации не поддерживаются."""
        directive = retry_action.directive
        if directive not in {"RETRY_BACKOFF", "RETRY_AFTER"}:
            return False, retries_used
        if not self._retry_engine.can_retry(retries_used):
            return False, retries_used

        retries_used += 1
        self._retries_total += 1
        delay = self._compute_retry_delay(directive, retry_after_s, retries_used)
        self._safe_logger.debug_retry(
            operation=operation,
            fault_kind=fault_kind,
            retries_used=retries_used,
            max_retries=self._retry_engine.max_retries,
            delay_s=delay,
            mutation=None,
        )
        return True, retries_used

    def _compute_retry_delay(
        self,
        directive: str,
        retry_after_s: float | None,
        retries_used: int,
    ) -> float:
        """Рассчитать и выполнить задержку перед повтором."""
        if directive == "RETRY_AFTER" and retry_after_s is not None:
            return self._retry_engine.sleep_exact(retry_after_s)
        return self._retry_engine.sleep_before_retry(retries_used)
