"""
Бенчмарк: горячий путь `runtime.check()` (успех/ошибка).

Запуск:
    .venv/bin/python tests/performance/target/bench_target_runtime_check.py --fast
"""

from __future__ import annotations

import pyperf

from connector.domain.diagnostics.policies import SystemErrorCode
from connector.infra.target.models import (
    TargetCheckResult,
    TargetConnectionConfig,
)
from connector.infra.target.runtime import DefaultTargetRuntime

N = 50_000


class StubGatewayOk:
    def health_check(self) -> TargetCheckResult:
        return TargetCheckResult(ok=True, latency_ms=1)

    def get_stats(self) -> tuple[int, int, int]:
        return (0, 0, 0)

    def reset_stats(self) -> None:
        return None


class StubGatewayFail:
    def health_check(self) -> TargetCheckResult:
        return TargetCheckResult(
            ok=False,
            latency_ms=1,
            fault_kind="TRANSIENT",
            error_code=SystemErrorCode.INFRA_UNAVAILABLE,
            error_message="unavailable",
        )

    def get_stats(self) -> tuple[int, int, int]:
        return (0, 0, 0)

    def reset_stats(self) -> None:
        return None


def _runtime(gateway: object) -> DefaultTargetRuntime:
    return DefaultTargetRuntime(
        gateway=gateway,  # type: ignore[arg-type]
        config=TargetConnectionConfig(
            target_type="ankey",
            base_url="https://bench.local",
            username="bench",
        ),
        has_reader=False,
    )


def bench_runtime_check_ok(loops: int) -> float:
    runtime = _runtime(StubGatewayOk())
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for _ in range(N):
            result = runtime.check()
            assert result.ok
        total += timer() - t0
    return total


def bench_runtime_check_fail(loops: int) -> float:
    runtime = _runtime(StubGatewayFail())
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for _ in range(N):
            result = runtime.check()
            assert not result.ok
        total += timer() - t0
    return total


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.bench_time_func("target_runtime_check_ok", bench_runtime_check_ok)
    runner.bench_time_func("target_runtime_check_fail", bench_runtime_check_fail)
