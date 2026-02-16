"""
Проверка запуска точек входа бенчмарков для target performance-набора.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.performance

ROOT = Path(__file__).resolve().parents[3]
PYTHON = ROOT / ".venv" / "bin" / "python"
BENCH_DIR = ROOT / "tests" / "performance" / "target"


def _run_bench(script_name: str) -> None:
    script = BENCH_DIR / script_name
    proc = subprocess.run(
        [
            str(PYTHON),
            str(script),
            "--fast",
            "-p",
            "1",
            "-n",
            "1",
            "-w",
            "0",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"{script_name} завершился с ошибкой:\n{proc.stdout}\n{proc.stderr}"


def test_bench_target_runtime_execute_overhead_entrypoint() -> None:
    _run_bench("bench_target_runtime_execute_overhead.py")


def test_bench_target_runtime_check_entrypoint() -> None:
    _run_bench("bench_target_runtime_check.py")


def test_bench_target_gateway_retry_transient_entrypoint() -> None:
    _run_bench("bench_target_gateway_retry_transient.py")


def test_bench_target_kernel_lookup_entrypoint() -> None:
    _run_bench("bench_target_kernel_operation_lookup.py")


def test_bench_target_redaction_safe_view_entrypoint() -> None:
    _run_bench("bench_target_redaction_safe_view.py")
