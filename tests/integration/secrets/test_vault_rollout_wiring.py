from __future__ import annotations

import json
from pathlib import Path

from cryptography.fernet import Fernet
from typer.testing import CliRunner

from connector.main import app

runner = CliRunner()


def _write_empty_plan(path: Path, *, run_id: str) -> None:
    payload = {
        "meta": {
            "run_id": run_id,
            "generated_at": "2026-02-18T00:00:00Z",
            "dataset": "employees",
            "csv_path": None,
            "plan_path": str(path),
            "include_deleted": False,
        },
        "summary": {
            "rows_total": 0,
            "valid_rows": 0,
            "failed_rows": 0,
            "planned_create": 0,
            "planned_update": 0,
            "skipped": 0,
        },
        "items": [],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_report(report_path: Path) -> dict:
    return json.loads(report_path.read_text(encoding="utf-8"))


def test_import_apply_staging_rollout_forces_dry_run(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_id = "stage9-rollout-staging"
    _write_empty_plan(plan_path, run_id=run_id)

    result = runner.invoke(
        app,
        [
            "--cache-dir",
            str(tmp_path / "cache"),
            "--log-dir",
            str(tmp_path / "logs"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--host",
            "api.local",
            "--port",
            "443",
            "--api-username",
            "user",
            "--api-password",
            "secret",
            "--run-id",
            run_id,
            "import",
            "apply",
            "--plan",
            str(plan_path),
            "--secrets-from",
            "vault",
        ],
        env={
            "ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{Fernet.generate_key().decode('utf-8')}",
            "ANKEY_VAULT_ROLLOUT_MODE": "staging_dry_run",
        },
    )
    assert result.exit_code == 0

    report = _read_report(tmp_path / "reports" / f"report_import-apply_{run_id}.json")
    apply_ctx = report.get("context", {}).get("apply", {})
    rollout_ctx = apply_ctx.get("vault_rollout", {})
    assert apply_ctx.get("dry_run") is True
    assert apply_ctx.get("configured_dry_run") is False
    assert rollout_ctx.get("mode") == "staging_dry_run"
    assert rollout_ctx.get("force_dry_run") is True


def test_import_apply_canary_percent_zero_blocks_requested_vault(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.json"
    run_id = "stage9-rollout-canary-block"
    _write_empty_plan(plan_path, run_id=run_id)

    result = runner.invoke(
        app,
        [
            "--cache-dir",
            str(tmp_path / "cache"),
            "--log-dir",
            str(tmp_path / "logs"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--host",
            "api.local",
            "--port",
            "443",
            "--api-username",
            "user",
            "--api-password",
            "secret",
            "--run-id",
            run_id,
            "import",
            "apply",
            "--plan",
            str(plan_path),
            "--secrets-from",
            "vault",
        ],
        env={
            "ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{Fernet.generate_key().decode('utf-8')}",
            "ANKEY_VAULT_ROLLOUT_MODE": "canary",
            "ANKEY_VAULT_CANARY_PERCENT": "0",
            "ANKEY_VAULT_CANARY_DATASETS": "employees",
        },
    )
    assert result.exit_code == 2
    assert "vault rollout policy blocks import-apply vault path" in result.output
