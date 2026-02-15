"""
Benchmark: TargetKernel operation lookup (classify_fault + retry_directive).

Run:
    .venv/bin/python tests/performance/target/bench_target_kernel_operation_lookup.py --fast
"""

from __future__ import annotations

import pyperf

from connector.infra.target.kernel import TargetKernel
from connector.infra.target.spec_ankey import build_ankey_spec

N = 200_000
STATUSES = (200, 401, 403, 404, 409, 429, 500, 503, 504, 418)
ERROR_CODES = (None, "NETWORK_ERROR")


def bench_kernel_lookup(loops: int) -> float:
    kernel = TargetKernel(build_ankey_spec())
    timer = pyperf.perf_counter
    total = 0.0
    for _ in range(loops):
        t0 = timer()
        for i in range(N):
            status = STATUSES[i % len(STATUSES)]
            err = ERROR_CODES[i % len(ERROR_CODES)]
            fault = kernel.classify_fault(status_code=status, error_code=err)
            _ = kernel.retry_directive(fault)
            _ = kernel.system_error_code(fault)
        total += timer() - t0
    return total


if __name__ == "__main__":
    runner = pyperf.Runner()
    runner.bench_time_func("target_kernel_lookup", bench_kernel_lookup)

