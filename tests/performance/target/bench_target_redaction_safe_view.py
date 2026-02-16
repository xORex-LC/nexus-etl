"""
Бенчмарк: редактирование и безопасное представление в `TargetKernel` для заголовков и payload.

Запуск:
    .venv/bin/python tests/performance/target/bench_target_redaction_safe_view.py --fast
"""

from __future__ import annotations

import pyperf

from connector.infra.target.core.kernel import TargetKernel
from connector.infra.target.providers.ankey_rest.spec import build_ankey_spec

SMALL = {
    "id": "u1",
    "name": "Alice",
    "password": "secret",
}
MEDIUM = {
    "users": [
        {"id": f"u{i}", "email": f"u{i}@example.org", "password": "secret"}
        for i in range(100)
    ]
}
LARGE = {
    "users": [
        {"id": f"u{i}", "email": f"u{i}@example.org", "password": "secret"}
        for i in range(1000)
    ]
}
HEADERS = {
    "Authorization": "Bearer token",
    "X-Ankey-Password": "secret",
    "Content-Type": "application/json",
}


def bench_redaction_small(loops: int) -> float:
    kernel = TargetKernel(build_ankey_spec())
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for _ in range(5_000):
            _ = kernel.redact_headers(HEADERS)
            _ = kernel.safe_body(SMALL)
        total += timer() - t0
    return total


def bench_redaction_medium(loops: int) -> float:
    kernel = TargetKernel(build_ankey_spec())
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for _ in range(300):
            _ = kernel.redact_headers(HEADERS)
            _ = kernel.safe_body(MEDIUM)
        total += timer() - t0
    return total


def bench_redaction_large(loops: int) -> float:
    kernel = TargetKernel(build_ankey_spec())
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for _ in range(40):
            _ = kernel.redact_headers(HEADERS)
            _ = kernel.safe_body(LARGE)
        total += timer() - t0
    return total


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.bench_time_func("target_redaction_small", bench_redaction_small)
    runner.bench_time_func("target_redaction_medium", bench_redaction_medium)
    runner.bench_time_func("target_redaction_large", bench_redaction_large)
