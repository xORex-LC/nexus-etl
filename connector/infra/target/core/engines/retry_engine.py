"""
Механизм retry для target-слоя на базе стратегий ожидания tenacity.

Политика (когда и почему ретраить) задаётся в TargetSpec + TargetKernel.
Этот модуль отвечает только за расчёт задержек/backoff и проверку бюджета повторов.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable

from tenacity.wait import wait_exponential, wait_exponential_jitter

from connector.infra.target.core.spec_models import RetryConfig


@dataclass(frozen=True, slots=True)
class _RetryAttemptState:
    attempt_number: int


class TargetRetryEngine:
    """
    Обёртка над механизмом backoff/jitter.

    Семантика:
        - `RetryConfig.max_attempts` — это бюджет повторов (без учёта первой попытки).
        - `retries_used` начинается с 0 до первого повтора.
    """

    def __init__(
        self,
        config: RetryConfig,
        *,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self._config = config
        self._sleep_fn = sleep_fn
        if config.jitter:
            # Ограниченный экспоненциальный backoff + добавочный jitter.
            self._wait_strategy = wait_exponential_jitter(
                initial=config.backoff_base,
                max=config.backoff_max,
                jitter=config.backoff_base,
            )
        else:
            # Детерминированный экспоненциальный backoff без jitter.
            self._wait_strategy = wait_exponential(
                multiplier=config.backoff_base,
                min=config.backoff_base,
                max=config.backoff_max,
            )

    @property
    def max_retries(self) -> int:
        return self._config.max_attempts

    def can_retry(self, retries_used: int) -> bool:
        return retries_used < self._config.max_attempts

    def sleep_before_retry(self, retries_used: int) -> float:
        """
        Подождать перед следующим повтором и вернуть рассчитанную задержку.

        Параметры:
            retries_used: число уже использованных повторов, >= 1.
        """
        attempt_number = max(1, retries_used)
        delay = float(self._wait_strategy(_RetryAttemptState(attempt_number=attempt_number)))
        if delay > 0:
            self._sleep_fn(delay)
        return delay

    def sleep_exact(self, delay_s: float | None) -> float:
        """Подождать фиксированную задержку (например, Retry-After)."""
        if delay_s is None:
            return 0.0
        delay = max(0.0, float(delay_s))
        if delay > 0:
            self._sleep_fn(delay)
        return delay
