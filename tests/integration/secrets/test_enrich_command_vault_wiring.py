from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet
from typer.testing import CliRunner

from connector.main import app

runner = CliRunner()

HEADER = "raw_id,full_name,login,email_or_phone,contacts,org,manager,flags,employment,extra"


def _write_minimal_employees_csv(path: Path) -> None:
    row = [
        "1001",
        "Doe John M",
        "jdoe",
        "john.doe@example.com",
        "+123456",
        "Org=Engineering",
        "",
        "disabled=false",
        "role=Engineer",
        "password=SECRET1;org_id=10;tab=5001",
    ]
    content = "\n".join([HEADER, ",".join(row)])
    path.write_text(content, encoding="utf-8")


def test_enrich_command_auto_mode_writes_secrets_to_sqlite_vault(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    _write_minimal_employees_csv(csv_path)

    cache_dir = tmp_path / "cache"
    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
    master_key = Fernet.generate_key().decode("utf-8")

    result = runner.invoke(
        app,
        [
            "--cache-dir",
            str(cache_dir),
            "--log-dir",
            str(log_dir),
            "--report-dir",
            str(report_dir),
            "--run-id",
            "vault-write",
            "enrich",
            "--csv-has-header",
        ],
        env={
            "EMPLOYEES_SOURCE_PATH": str(csv_path),
            "ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{master_key}",
        },
    )

    assert result.exit_code == 0

    report_path = report_dir / "report_enrich_vault-write.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    dictionary_ctx = report.get("context", {}).get("dictionary")
    assert isinstance(dictionary_ctx, dict)
    assert dictionary_ctx.get("component") == "dictionary"
    assert dictionary_ctx.get("backend") == "polars"
    assert "aggregate" in dictionary_ctx
    assert "dictionaries_detail" in dictionary_ctx
    org_detail = dictionary_ctx["dictionaries_detail"].get("organizations")
    assert isinstance(org_detail, dict)
    assert org_detail.get("row_count") is not None
    assert org_detail.get("fingerprint_kind") == "content_sha256"
    assert isinstance(org_detail.get("version_info"), dict)

    vault_db_path = cache_dir / "ankey_vault.sqlite3"
    assert vault_db_path.exists()

    conn = sqlite3.connect(str(vault_db_path))
    try:
        row = conn.execute(
            """
            SELECT ciphertext
            FROM vault_secrets
            WHERE dataset = 'employees' AND field = 'password'
            LIMIT 1
            """
        ).fetchone()
        assert row is not None
        ciphertext = row[0]
        if isinstance(ciphertext, bytes):
            assert b"SECRET1" not in ciphertext
        else:
            assert "SECRET1" not in str(ciphertext)
    finally:
        conn.close()


def test_enrich_command_fails_when_vault_mode_off_and_dataset_has_secret_fields(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    _write_minimal_employees_csv(csv_path)

    result = runner.invoke(
        app,
        [
            "--cache-dir",
            str(tmp_path / "cache"),
            "--log-dir",
            str(tmp_path / "logs"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--run-id",
            "vault-off",
            "enrich",
            "--csv-has-header",
            "--vault-mode",
            "off",
        ],
        env={
            "EMPLOYEES_SOURCE_PATH": str(csv_path),
            "ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{Fernet.generate_key().decode('utf-8')}",
        },
    )

    assert result.exit_code == 2
    assert "vault-mode=off cannot be used" in result.output
