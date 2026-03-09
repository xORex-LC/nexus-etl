"""Smoke-тест pyperf benchmark entrypoint для vault-management lifecycle."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest


pytestmark = pytest.mark.performance

ROOT = Path(__file__).resolve().parents[3]
PYTHON = ROOT / ".venv" / "bin" / "python"


def test_vault_management_lifecycle_pyperf_entrypoint_fast(tmp_path: Path) -> None:
    script = ROOT / "tests" / "performance" / "vault" / "bench_vault_management_lifecycle_pyperf.py"
    output_file = tmp_path / "vault_mgmt_pyperf.json"

    proc = subprocess.run(
        [
            str(PYTHON),
            str(script),
            "--fast",
            "--output",
            str(output_file),
        ],
        capture_output=True,
        text=True,
    )

    assert proc.returncode == 0, proc.stdout + "\n" + proc.stderr
    assert output_file.exists()

