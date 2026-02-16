"""
Benchmark: compare direct gateway.execute vs runtime.executor.execute.

Run:
    .venv/bin/python tests/performance/target/bench_target_runtime_execute_overhead.py --fast
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterator

import pyperf

from connector.domain.ports.target.execution import RequestSpec
from connector.infra.target.driver import DriverResponse
from connector.infra.target.gateway import TargetGateway
from connector.infra.target.kernel import TargetKernel
from connector.infra.target.models import TargetConnectionConfig
from connector.infra.target.runtime import DefaultTargetRuntime
from connector.infra.target.spec_ankey import build_ankey_spec

N = 500


class AlwaysOkDriver:
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> DriverResponse:
        return DriverResponse(status_code=200, body={"id": "u-1"}, body_snippet=None)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return {"ok": True}

    def get_paged_items(
        self,
        path: str,
        page_size: int,
        max_pages: int | None,
        params: dict[str, Any] | None = None,
    ) -> Iterator[tuple[int, list[Any]]]:
        return iter(())


def _build_gateway() -> TargetGateway:
    spec = build_ankey_spec()
    spec = replace(
        spec,
        retry_config=replace(
            spec.retry_config,
            max_attempts=0,
            backoff_base=0.0,
            backoff_max=0.0,
            jitter=False,
        ),
    )
    return TargetGateway(AlwaysOkDriver(), TargetKernel(spec))  # type: ignore[arg-type]


SPEC = RequestSpec(method="POST", path="/users", expected_statuses=(200,))


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
            base_url="https://bench.local",
            username="bench",
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
