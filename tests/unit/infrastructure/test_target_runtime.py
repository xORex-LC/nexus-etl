from __future__ import annotations

from connector.infra.target.core.models import (
    TargetCheckResult,
    TargetConnectionConfig,
    TargetMeta,
    TargetStats,
)
from connector.infra.target.core.runtime import DefaultTargetRuntime


class StubGateway:
    def __init__(self) -> None:
        self.health = TargetCheckResult(ok=True, latency_ms=7)
        self.stats = (11, 3, 2)
        self.reset_called = False
        self.close_called = False

    def health_check(self) -> TargetCheckResult:
        return self.health

    def get_stats(self) -> tuple[int, int, int]:
        return self.stats

    def reset_stats(self) -> None:
        self.reset_called = True

    def close(self) -> None:
        self.close_called = True


def _config() -> TargetConnectionConfig:
    return TargetConnectionConfig(
        target_type="ankey",
        base_url="https://ankey.example:8443",
        username="svc-user",
        transport="http",
    )


def test_runtime_exposes_executor_and_reader_when_enabled() -> None:
    gateway = StubGateway()
    runtime = DefaultTargetRuntime(
        gateway=gateway,  # type: ignore[arg-type]
        config=_config(),
        has_reader=True,
    )

    assert runtime.executor is gateway
    assert runtime.reader is gateway


def test_runtime_reader_is_none_when_disabled() -> None:
    gateway = StubGateway()
    runtime = DefaultTargetRuntime(
        gateway=gateway,  # type: ignore[arg-type]
        config=_config(),
        has_reader=False,
    )

    assert runtime.reader is None


def test_runtime_meta_returns_typed_model() -> None:
    gateway = StubGateway()
    runtime = DefaultTargetRuntime(
        gateway=gateway,  # type: ignore[arg-type]
        config=_config(),
        has_reader=False,
    )

    assert runtime.meta() == TargetMeta(
        target_type="ankey",
        base_url="https://ankey.example:8443",
        transport="http",
    )


def test_runtime_stats_returns_typed_model() -> None:
    gateway = StubGateway()
    runtime = DefaultTargetRuntime(
        gateway=gateway,  # type: ignore[arg-type]
        config=_config(),
        has_reader=False,
    )

    assert runtime.stats() == TargetStats(
        requests_total=11,
        retries_total=3,
        failures_total=2,
    )


def test_runtime_check_delegates_to_gateway() -> None:
    gateway = StubGateway()
    runtime = DefaultTargetRuntime(
        gateway=gateway,  # type: ignore[arg-type]
        config=_config(),
        has_reader=False,
    )

    assert runtime.check() is gateway.health


def test_runtime_reset_delegates_to_gateway() -> None:
    gateway = StubGateway()
    runtime = DefaultTargetRuntime(
        gateway=gateway,  # type: ignore[arg-type]
        config=_config(),
        has_reader=False,
    )

    runtime.reset()

    assert gateway.reset_called is True


def test_runtime_close_delegates_to_gateway() -> None:
    gateway = StubGateway()
    runtime = DefaultTargetRuntime(
        gateway=gateway,  # type: ignore[arg-type]
        config=_config(),
        has_reader=False,
    )

    runtime.close()

    assert gateway.close_called is True
