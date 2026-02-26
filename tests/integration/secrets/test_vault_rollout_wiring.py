from __future__ import annotations

from connector.config.models import AppConfig
from connector.config.projections import to_vault_db_config
import json
from pathlib import Path

from cryptography.fernet import Fernet
from typer.testing import CliRunner

from connector.domain.secrets.secret_locator_service import SecretLocatorService
from connector.domain.secrets.secret_vault_write_service import SecretVaultWriteService
from connector.infra.secrets import EnvVaultKeyProvider, FernetEnvelopeCipher
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.sqlite.engine import open_sqlite
from connector.main import app

runner = CliRunner()
_MATCH_KEY = "Doe|John|M|100"


def _base_desired_state() -> dict[str, object]:
    return {
        "email": "user@example.com",
        "last_name": "Doe",
        "first_name": "John",
        "middle_name": "M",
        "is_logon_disable": False,
        "user_name": "jdoe",
        "phone": "+1111111",
        "password": "",
        "personnel_number": "100",
        "manager_id": None,
        "organization_id": 20,
        "position": "Engineer",
        "avatar_id": None,
        "usr_org_tab_num": "TAB-100",
    }


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


def _write_ephemeral_plan(path: Path, *, run_id: str) -> None:
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
            "rows_total": 1,
            "valid_rows": 1,
            "failed_rows": 0,
            "planned_create": 1,
            "planned_update": 0,
            "skipped": 0,
        },
        "items": [
            {
                "row_id": "row-1",
                "line_no": 1,
                "op": "create",
                "target_id": "target-1",
                "desired_state": _base_desired_state(),
                "changes": {},
                "source_ref": {"match_key": _MATCH_KEY},
                "secret_fields": ["password"],
                "secret_lifecycle": {"mode": "ephemeral", "delete_on_success": True},
            }
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _seed_vault_secret(*, tmp_path: Path, run_id: str) -> None:
    engine = open_sqlite(
        to_vault_db_config(AppConfig()),
        str(tmp_path / "cache" / "ankey_vault.sqlite3"),
    )
    try:
        store = SecretVaultWriteService(
            repository=SqliteVaultRepository(engine),
            cipher=FernetEnvelopeCipher(),
            key_provider=EnvVaultKeyProvider(),
            locator=SecretLocatorService(),
        )
        store.put_many(
            dataset="employees",
            match_key=_MATCH_KEY,
            secrets={"password": "TopSecret123"},
            run_id=run_id,
        )
    finally:
        engine.close()


def _vault_secret_exists(*, tmp_path: Path, run_id: str) -> bool:
    engine = open_sqlite(
        to_vault_db_config(AppConfig()),
        str(tmp_path / "cache" / "ankey_vault.sqlite3"),
    )
    try:
        repo = SqliteVaultRepository(engine)
        locator_hash = SecretLocatorService().build_locator_hash(
            dataset="employees",
            field="password",
            source_ref={"match_key": _MATCH_KEY},
        )
        record = repo.get_secret(
            dataset="employees",
            field="password",
            locator_hash=locator_hash,
            locator_version="v1",
            run_id=run_id,
        )
        return record is not None
    finally:
        engine.close()


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
            "--vault-mode",
            "on",
        ],
        env={
            "ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{Fernet.generate_key().decode('utf-8')}",
            "ANKEY_VAULT_ROLLOUT__MODE": "staging_dry_run",
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


def test_import_apply_explicit_dry_run_keeps_ephemeral_secret(tmp_path: Path, monkeypatch) -> None:
    plan_path = tmp_path / "plan.json"
    run_id = "stage9-rollout-dry-run-no-retention"
    _write_ephemeral_plan(plan_path, run_id=run_id)

    master_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("ANKEY_VAULT_MASTER_KEYS", f"mk_2026:{master_key}")
    _seed_vault_secret(tmp_path=tmp_path, run_id=run_id)

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
            "--dry-run",
            "--vault-mode",
            "on",
        ],
        env={"ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{master_key}"},
    )
    assert result.exit_code == 0
    assert _vault_secret_exists(tmp_path=tmp_path, run_id=run_id) is True

    report = _read_report(tmp_path / "reports" / f"report_import-apply_{run_id}.json")
    apply_ctx = report.get("context", {}).get("apply", {})
    assert apply_ctx.get("dry_run") is True
    assert apply_ctx.get("retention_stats") == {}
    assert apply_ctx.get("vault_maintenance") == {}


def test_import_apply_staging_dry_run_keeps_ephemeral_secret(tmp_path: Path, monkeypatch) -> None:
    plan_path = tmp_path / "plan.json"
    run_id = "stage9-rollout-staging-no-retention"
    _write_ephemeral_plan(plan_path, run_id=run_id)

    master_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setenv("ANKEY_VAULT_MASTER_KEYS", f"mk_2026:{master_key}")
    _seed_vault_secret(tmp_path=tmp_path, run_id=run_id)

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
            "--vault-mode",
            "on",
        ],
        env={
            "ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{master_key}",
            "ANKEY_VAULT_ROLLOUT__MODE": "staging_dry_run",
        },
    )
    assert result.exit_code == 0
    assert _vault_secret_exists(tmp_path=tmp_path, run_id=run_id) is True

    report = _read_report(tmp_path / "reports" / f"report_import-apply_{run_id}.json")
    apply_ctx = report.get("context", {}).get("apply", {})
    rollout_ctx = apply_ctx.get("vault_rollout", {})
    assert apply_ctx.get("dry_run") is True
    assert apply_ctx.get("configured_dry_run") is False
    assert apply_ctx.get("retention_stats") == {}
    assert apply_ctx.get("vault_maintenance") == {}
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
            "--vault-mode",
            "on",
        ],
        env={
            "ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{Fernet.generate_key().decode('utf-8')}",
            "ANKEY_VAULT_ROLLOUT__MODE": "canary",
            "ANKEY_VAULT_ROLLOUT__CANARY_PERCENT": "0",
            "ANKEY_VAULT_ROLLOUT__CANARY_DATASETS": "employees",
        },
    )
    assert result.exit_code == 2
    assert "vault rollout policy blocks import-apply vault path" in result.output
