"""
Smoke-тесты entrypoint-скриптов performance-бенчмарков apply.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.performance

ROOT = Path(__file__).resolve().parents[3]
PYTHON = ROOT / ".venv" / "bin" / "python"


def _run_bench(script_name: str) -> None:
    script = ROOT / "tests" / "performance" / "apply" / script_name
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
    assert proc.returncode == 0, f"{script_name} failed:\n{proc.stdout}\n{proc.stderr}"


def test_bench_apply_all_ok_entrypoint() -> None:
    _run_bench("bench_apply_usecase_summary_only.py")


def test_bench_apply_all_error_bounded_entrypoint() -> None:
    _run_bench("bench_apply_usecase_warn_error_buffered.py")


def test_bench_presenter_entrypoint() -> None:
    _run_bench("bench_presenter_build_report.py")
