"""Smoke-тест Stage-09 бенчмарк-харнеса для vault rollout."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

pytestmark = pytest.mark.performance

ROOT = Path(__file__).resolve().parents[3]
PYTHON = ROOT / ".venv" / "bin" / "python"


def test_vault_rollout_benchmark_entrypoint_fast(tmp_path: Path) -> None:
    script = ROOT / "tests" / "performance" / "vault" / "bench_vault_rollout_gate.py"
    proc = subprocess.run(
        [
            str(PYTHON),
            str(script),
            "--fast",
            "--run-id",
            "stage09-fast",
            "--out-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert (tmp_path / "vault_benchmark_stage09-fast.json").exists()
    assert (tmp_path / "vault_benchmark_stage09-fast.md").exists()
