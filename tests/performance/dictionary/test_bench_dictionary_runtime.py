"""
Smoke-проверка entrypoint dictionary performance benchmarks.
"""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.performance

ROOT = Path(__file__).resolve().parents[3]
PYTHON = ROOT / ".venv" / "bin" / "python"
BENCH_DIR = ROOT / "tests" / "performance" / "dictionary"


def test_bench_dictionary_runtime_v1_entrypoint() -> None:
    script = BENCH_DIR / "bench_dictionary_runtime_v1.py"
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
    assert proc.returncode == 0, f"dictionary bench завершился с ошибкой:\n{proc.stdout}\n{proc.stderr}"
