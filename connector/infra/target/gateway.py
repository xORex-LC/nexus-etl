"""
TargetGateway — единственный владелец retry-политики.

Назначение:
    Переводит потребности приложения в операции target, используя
    TargetKernel для классификации и TargetDriver для I/O.

Контракт:
    - Structurally satisfies RequestExecutorProtocol (execute).
    - Structurally satisfies TargetPagedReaderProtocol (iter_pages).
    - Retry только для RETRY_BACKOFF / RETRY_AFTER по fault_rules.
    - Никогда не бросает исключений наружу (нормализует в result-объекты).
"""

from __future__ import annotations

import random
import time
from typing import Any, Iterable

from connector.common.sanitize import maskSecretsInObject, truncateText
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.target.execution import ExecutionResult, RequestSpec
from connector.domain.ports.target.read import TargetPageResult
from connector.infra.http.ankey_client import ApiError
from connector.infra.target.driver import AnkeyHttpDriver, DriverError
from connector.infra.target.kernel import TargetKernel
from connector.infra.target.models import TargetCheckResult
from connector.infra.target.spec import RetryConfig


class TargetGateway:
    """
    Назначение:
        Единственный владелец retry-политики для target-операций.

    Взаимодействия:
        - TargetDriver: single-attempt I/O.
        - TargetKernel: classify_fault → retry_directive → system_error_code.
    """

    def __init__(self, driver: AnkeyHttpDriver, kernel: TargetKernel) -> None:
        self._driver = driver
        self._kernel = kernel
        self._requests_total: int = 0
        self._retries_total: int = 0
        self._failures_total: int = 0

    # ------------------------------------------------------------------
    # RequestExecutorProtocol
    # ------------------------------------------------------------------

    def execute(self, spec: RequestSpec) -> ExecutionResult:
        """
        Выполнить RequestSpec с retry по spec.retry_rules. Никогда не бросает.
        """
        retry_cfg = self._kernel.spec.retry_config
        attempt = 0

        while True:
            self._requests_total += 1

            try:
                resp = self._driver.request(
                    spec.method,
                    spec.path,
                    params=spec.query,
                    json=spec.payload,
                    headers=spec.headers,
                )
            except DriverError as exc:
                fault = self._kernel.classify_fault(error_code=exc.code)
                directive = self._kernel.retry_directive(fault)
                if directive == "RETRY_BACKOFF" and attempt < retry_cfg.max_attempts:
                    self._retries_total += 1
                    self._backoff_sleep(attempt, retry_cfg)
                    attempt += 1
                    continue
                self._failures_total += 1
                return ExecutionResult(
                    ok=False,
                    status_code=None,
                    response_json=None,
                    error_code=self._kernel.system_error_code(fault),
                    error_message=truncateText(str(exc)),
                )

            if spec.is_expected(resp.status_code):
                safe_body = self._sanitize(resp.body)
                safe_json = safe_body if isinstance(safe_body, (dict, list)) else None
                return ExecutionResult(
                    ok=True,
                    status_code=resp.status_code,
                    response_json=safe_json,
                )

            fault = self._kernel.classify_fault(status_code=resp.status_code)
            directive = self._kernel.retry_directive(fault)
            if directive == "RETRY_BACKOFF" and attempt < retry_cfg.max_attempts:
                self._retries_total += 1
                self._backoff_sleep(attempt, retry_cfg)
                attempt += 1
                continue

            self._failures_total += 1
            reason = self._detect_error_reason(resp.body, resp.body_snippet)
            safe_snippet = truncateText(resp.body_snippet) if resp.body_snippet else None
            details: dict[str, Any] | None = None
            if safe_snippet:
                details = {"body_snippet": safe_snippet}
            safe_json = self._sanitize(resp.body) if isinstance(resp.body, (dict, list)) else None
            if safe_json is not None:
                details = details or {}
                details["response_json"] = safe_json

            return ExecutionResult(
                ok=False,
                status_code=resp.status_code,
                response_json=safe_json,
                error_code=self._kernel.system_error_code(fault),
                error_message=f"HTTP {resp.status_code}",
                error_reason=reason,
                error_details=details,
            )

    # ------------------------------------------------------------------
    # TargetPagedReaderProtocol
    # ------------------------------------------------------------------

    def iter_pages(
        self,
        path: str,
        page_size: int,
        max_pages: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterable[TargetPageResult]:
        """
        Чтение страниц из target. Нормализует ошибки в TargetPageResult.
        """
        params = params or {}
        retry_cfg = self._kernel.spec.retry_config
        attempt = 0
        last_page = 0

        while True:
            try:
                for page, items in self._driver.get_paged_items(path, page_size, max_pages):
                    self._requests_total += 1
                    last_page = page
                    safe_items = maskSecretsInObject(items)
                    yield TargetPageResult(ok=True, page=page, items=safe_items)
                return
            except DriverError as exc:
                fault = self._kernel.classify_fault(error_code=exc.code)
                directive = self._kernel.retry_directive(fault)
                # Если страницы уже начали выдавать — не ретраим, чтобы не дублировать данные.
                if (
                    last_page == 0
                    and directive == "RETRY_BACKOFF"
                    and attempt < retry_cfg.max_attempts
                ):
                    self._retries_total += 1
                    self._backoff_sleep(attempt, retry_cfg)
                    attempt += 1
                    continue

                self._failures_total += 1
                yield TargetPageResult(
                    ok=False,
                    page=last_page,
                    items=None,
                    error_code=self._kernel.system_error_code(fault),
                    error_message=str(exc),
                )
                return
            except ApiError as exc:
                fault = self._kernel.classify_fault(
                    status_code=exc.status_code, error_code=exc.code,
                )
                directive = self._kernel.retry_directive(fault)
                # Если страницы уже начали выдавать — не ретраим, чтобы не дублировать данные.
                if (
                    last_page == 0
                    and directive == "RETRY_BACKOFF"
                    and attempt < retry_cfg.max_attempts
                ):
                    self._retries_total += 1
                    self._backoff_sleep(attempt, retry_cfg)
                    attempt += 1
                    continue

                self._failures_total += 1
                error_details: dict[str, Any] | None = None
                if isinstance(exc.details, dict):
                    error_details = maskSecretsInObject(exc.details)
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
                    error_code=self._kernel.system_error_code(fault),
                    error_message=truncateText(str(exc)),
                    error_details=error_details or None,
                )
                return

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def health_check(self) -> TargetCheckResult:
        """Health-check через spec.health_check."""
        hc = self._kernel.spec.health_check
        start = time.monotonic()
        try:
            self._driver.get_json(hc.path, hc.params)
            latency_ms = int((time.monotonic() - start) * 1000)
            return TargetCheckResult(ok=True, latency_ms=latency_ms)
        except (DriverError, ApiError) as exc:
            latency_ms = int((time.monotonic() - start) * 1000)
            status = getattr(exc, "status_code", None)
            code = getattr(exc, "code", None)
            fault = self._kernel.classify_fault(status_code=status, error_code=code)
            return TargetCheckResult(
                ok=False,
                latency_ms=latency_ms,
                fault_kind=fault,
                error_code=self._kernel.system_error_code(fault),
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
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> tuple[int, int, int]:
        """(requests_total, retries_total, failures_total)."""
        return (self._requests_total, self._retries_total, self._failures_total)

    def reset_stats(self) -> None:
        self._requests_total = 0
        self._retries_total = 0
        self._failures_total = 0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _backoff_sleep(attempt: int, cfg: RetryConfig) -> None:
        """Exponential backoff with jitter."""
        delay = min(cfg.backoff_base * (2**attempt), cfg.backoff_max)
        if cfg.jitter:
            delay *= random.uniform(0.5, 1.0)
        time.sleep(delay)

    @staticmethod
    def _sanitize(payload: Any) -> Any:
        if isinstance(payload, str):
            return truncateText(payload)
        return maskSecretsInObject(payload)

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
