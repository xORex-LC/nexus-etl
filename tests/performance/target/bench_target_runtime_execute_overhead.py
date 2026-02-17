"""
Бенчмарк: сравнение прямого `gateway.execute` и `runtime.executor.execute`.

Запуск:
    .venv/bin/python tests/performance/target/bench_target_runtime_execute_overhead.py --fast
"""

from __future__ import annotations

from typing import Any, Iterator

import pyperf

from connector.domain.ports.target.execution import RequestSpec
from connector.infra.target.driver import DriverResponse
from connector.infra.target.core.gateway import TargetGateway
from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.core.models import TargetConnectionConfig
from connector.infra.target.core.runtime import DefaultTargetRuntime
from connector.infra.target.providers.ankey_rest.provider import build_transport_compiler_registry
from connector.infra.target.providers.ankey_rest.spec import build_ankey_spec

N = 500


class AlwaysOkDriver:
    def execute(
        self,
        compiled_request: Any,
        payload: Any | None = None,
    ) -> DriverResponse:
        return DriverResponse(ok=True, status_code=200, body={"id": "u-1"}, body_snippet=None)

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


def _build_gateway() -> TargetGateway:
    spec = build_ankey_spec()
    spec = spec.model_copy(
        update={
            "retry_config": spec.retry_config.model_copy(
                update={
                    "max_attempts": 0,
                    "backoff_base": 0.0,
                    "backoff_max": 0.0,
                    "jitter": False,
                },
            )
        },
    )
    return TargetGateway(
        AlwaysOkDriver(),
        TargetKernel(
            spec,
            compiler_registry=build_transport_compiler_registry(),
        ),
    )  # type: ignore[arg-type]


SPEC = RequestSpec.operation(
    alias="users.upsert",
    params={"target_id": "bench-user"},
    payload={"name": "Bench"},
)


def bench_direct_execute(loops: int) -> float:
    gateway = _build_gateway()
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for _ in range(N):
            result = gateway.execute(SPEC)
            assert result.ok
        total += timer() - t0
    return total


def bench_runtime_execute(loops: int) -> float:
    gateway = _build_gateway()
    runtime = DefaultTargetRuntime(
        gateway=gateway,
        config=TargetConnectionConfig(
            target_type="ankey",
            endpoint="https://bench.local",
            transport="http",
        ),
        has_reader=False,
    )
    executor = runtime.executor
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for _ in range(N):
            result = executor.execute(SPEC)
            assert result.ok
        total += timer() - t0
    return total


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.bench_time_func(f"target_direct_execute_{N}", bench_direct_execute)
    runner.bench_time_func(f"target_runtime_execute_{N}", bench_runtime_execute)
