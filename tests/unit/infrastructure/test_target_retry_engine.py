from __future__ import annotations

from connector.infra.target.engines.retry_engine import TargetRetryEngine
from connector.infra.target.spec import RetryConfig


def test_can_retry_respects_retry_budget() -> None:
    engine = TargetRetryEngine(
        RetryConfig(max_attempts=2, backoff_base=0.1, backoff_max=1.0, jitter=False),
        sleep_fn=lambda _: None,
    )

    assert engine.can_retry(0) is True
    assert engine.can_retry(1) is True
    assert engine.can_retry(2) is False


def test_sleep_before_retry_follows_exponential_schedule_without_jitter() -> None:
    sleeps: list[float] = []
    engine = TargetRetryEngine(
        RetryConfig(max_attempts=3, backoff_base=0.2, backoff_max=0.5, jitter=False),
        sleep_fn=sleeps.append,
    )

    delay_1 = engine.sleep_before_retry(1)
    delay_2 = engine.sleep_before_retry(2)
    delay_3 = engine.sleep_before_retry(3)

    assert delay_1 == 0.2
    assert delay_2 == 0.4
    assert delay_3 == 0.5
    assert sleeps == [delay_1, delay_2, delay_3]


def test_sleep_before_retry_treats_zero_retries_as_first_attempt() -> None:
    sleeps: list[float] = []
    engine = TargetRetryEngine(
        RetryConfig(max_attempts=1, backoff_base=0.3, backoff_max=1.0, jitter=False),
        sleep_fn=sleeps.append,
    )

    delay = engine.sleep_before_retry(0)

    assert delay == 0.3
    assert sleeps == [0.3]
