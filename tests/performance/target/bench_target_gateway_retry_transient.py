"""
Benchmark: gateway retry engine (transient recovery vs no-retry auth failure).

Run:
    .venv/bin/python tests/performance/target/bench_target_gateway_retry_transient.py --fast
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Iterator

import pyperf

from connector.domain.ports.target.execution import RequestSpec
from connector.infra.target.driver import DriverResponse
from connector.infra.target.gateway import TargetGateway
from connector.infra.target.kernel import TargetKernel
from connector.infra.target.spec_ankey import build_ankey_spec

N = 1_000
SPEC = RequestSpec(method="POST", path="/users", expected_statuses=(200,))


def _spec_no_sleep():
    spec = build_ankey_spec()
    return replace(
        spec,
        retry_config=replace(
            spec.retry_config,
            max_attempts=2,
            backoff_base=0.0,
            backoff_max=0.0,
            jitter=False,
        ),
    )


class RetryRecoveryDriver:
    """On each execute(): first 503 then 200."""

    def __init__(self) -> None:
        self.calls = 0

    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> DriverResponse:
        self.calls += 1
        if self.calls % 2 == 1:
            return DriverResponse(status_code=503, body={"error": "tmp"}, body_snippet="tmp")
        return DriverResponse(status_code=200, body={"ok": True}, body_snippet=None)

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return {"ok": True}

    def get_paged_items(
        self, path: str, page_size: int, max_pages: int | None
    ) -> Iterator[tuple[int, list[Any]]]:
        return iter(())


class AuthFailDriver:
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any | None = None,
        headers: dict[str, str] | None = None,
    ) -> DriverResponse:
        return DriverResponse(status_code=401, body={"error": "auth"}, body_snippet="auth")

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return {"ok": True}

    def get_paged_items(
        self, path: str, page_size: int, max_pages: int | None
    ) -> Iterator[tuple[int, list[Any]]]:
        return iter(())


def bench_gateway_retry_recovery(loops: int) -> float:
    gateway = TargetGateway(RetryRecoveryDriver(), TargetKernel(_spec_no_sleep()))  # type: ignore[arg-type]
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
    gateway = TargetGateway(AuthFailDriver(), TargetKernel(_spec_no_sleep()))  # type: ignore[arg-type]
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for _ in range(N):
            result = gateway.execute(SPEC)
            assert not result.ok
            assert result.status_code == 401
        total += timer() - t0
    return total


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.bench_time_func("target_gateway_retry_recovery", bench_gateway_retry_recovery)
    runner.bench_time_func("target_gateway_no_retry_auth_fail", bench_gateway_no_retry_auth_fail)

