"""
Бенчмарк: retry-механизм `gateway` (восстановление после временной ошибки против auth-ошибки без ретрая).

Запуск:
    .venv/bin/python tests/performance/target/bench_target_gateway_retry_transient.py --fast
"""

from __future__ import annotations

from typing import Any, Iterator

import pyperf

from connector.domain.ports.target.execution import RequestSpec
from connector.infra.target.driver import DriverResponse
from connector.infra.target.core.gateway import TargetGateway
from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.providers.ankey_rest.provider import build_transport_compiler_registry
from connector.domain.target_dsl import load_target_spec

N = 1_000
SPEC = RequestSpec.operation(
    alias="users.upsert",
    params={"target_id": "bench-user"},
    payload={"name": "Bench"},
)


def _spec_no_sleep():
    spec = load_target_spec("ankey")
    return spec.model_copy(
        update={
            "retry_config": spec.retry_config.model_copy(
                update={
                    "max_attempts": 2,
                    "backoff_base": 0.0,
                    "backoff_max": 0.0,
                    "jitter": False,
                },
            )
        },
    )


class RetryRecoveryDriver:
    """На каждом execute(): сначала 503, затем 200."""

    def __init__(self) -> None:
        self.calls = 0

    def execute(
        self,
        compiled_request: Any,
        payload: Any | None = None,
    ) -> DriverResponse:
        self.calls += 1
        if self.calls % 2 == 1:
            return DriverResponse(ok=False, answer_code=503, payload={"error": "tmp"}, content_preview="tmp")
        return DriverResponse(ok=True, answer_code=200, payload={"ok": True}, content_preview=None)

    def iter_batches(
        self,
        compiled_request: Any,
        batch_size: int,
        max_batches: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]:
        return iter(())

    def close(self) -> None:
        pass


class AuthFailDriver:
    def execute(
        self,
        compiled_request: Any,
        payload: Any | None = None,
    ) -> DriverResponse:
        return DriverResponse(ok=False, answer_code=401, payload={"error": "auth"}, content_preview="auth")

    def iter_batches(
        self,
        compiled_request: Any,
        batch_size: int,
        max_batches: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]:
        return iter(())

    def close(self) -> None:
        pass


def bench_gateway_retry_recovery(loops: int) -> float:
    gateway = TargetGateway(
        RetryRecoveryDriver(),
        TargetKernel(
            _spec_no_sleep(),
            compiler_registry=build_transport_compiler_registry(),
        ),
    )  # type: ignore[arg-type]
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for _ in range(N):
            result = gateway.execute(SPEC)
            assert result.ok
        total += timer() - t0
    return total


def bench_gateway_no_retry_auth_fail(loops: int) -> float:
    gateway = TargetGateway(
        AuthFailDriver(),
        TargetKernel(
            _spec_no_sleep(),
            compiler_registry=build_transport_compiler_registry(),
        ),
    )  # type: ignore[arg-type]
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for _ in range(N):
            result = gateway.execute(SPEC)
            assert not result.ok
            assert result.answer_code == 401
        total += timer() - t0
    return total


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.bench_time_func("target_gateway_retry_recovery", bench_gateway_retry_recovery)
    runner.bench_time_func("target_gateway_no_retry_auth_fail", bench_gateway_no_retry_auth_fail)
