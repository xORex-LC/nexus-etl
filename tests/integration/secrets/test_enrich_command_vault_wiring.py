from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from typer.testing import CliRunner

from connector.main import app
from tests.integration.secrets._temp_registry import build_temp_employees_registry_with_temp_dictionaries
from tests.vault_unseal_setup import TEST_UNSEAL_PASSPHRASE, initialize_test_vault

runner = CliRunner()

HEADER = ";".join(
    [
        "Таб.№",
        "Пользователи",
        "Орг. единица уровня 1",
        "Орг. единица уровня 2",
        "Орг. единица уровня 3",
        "Орг. единица уровня 4",
        "Орг. единица уровня 5",
        "Организационная единица",
        "Штатная должность",
        "Поступл.",
        "Contract Number",
        "Догвр:нач.",
        "Название руководящей должности",
        "ДатаРожд",
        "Пол",
    ]
)


def _write_minimal_employees_csv(path: Path) -> None:
    row = [
        "1001",
        "Doe John M",
        "",
        "",
        "",
        "",
        "",
        "Org 10",
        "Engineer",
        "",
        "+123456",
        "",
        "",
        "",
        "",
    ]
    content = "\n".join([HEADER, ";".join(row)])
    path.write_text(content, encoding="utf-8")


def test_enrich_command_auto_mode_writes_secrets_to_sqlite_vault(tmp_path: Path):
    registry_path, (units_dictionary_name, titles_dictionary_name) = (
        build_temp_employees_registry_with_temp_dictionaries(tmp_path)
    )
    csv_path = tmp_path / "employees.csv"
    _write_minimal_employees_csv(csv_path)

    cache_dir = tmp_path / "cache"
    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
    initialize_test_vault(cache_dir)

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
        ],
        env={
            "EMPLOYEES_SOURCE_PATH": str(csv_path),
            "ANKEY_DATASET__REGISTRY_PATH": str(registry_path),
        },
        input=f"{TEST_UNSEAL_PASSPHRASE}\n",
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
    units_detail = dictionary_ctx["dictionaries_detail"].get(units_dictionary_name)
    titles_detail = dictionary_ctx["dictionaries_detail"].get(titles_dictionary_name)
    assert isinstance(units_detail, dict)
    assert isinstance(titles_detail, dict)
    assert units_detail.get("row_count") is not None
    assert units_detail.get("fingerprint_kind") == "content_sha256"
    assert isinstance(units_detail.get("version_info"), dict)
    assert titles_detail.get("row_count") is not None
    assert titles_detail.get("fingerprint_kind") == "content_sha256"
    assert isinstance(titles_detail.get("version_info"), dict)

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
    registry_path, _ = build_temp_employees_registry_with_temp_dictionaries(tmp_path)
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
            "--vault-mode",
            "off",
        ],
        env={
            "EMPLOYEES_SOURCE_PATH": str(csv_path),
            "ANKEY_DATASET__REGISTRY_PATH": str(registry_path),
        },
    )

    assert result.exit_code == 2
    assert "vault-mode=off cannot be used" in result.output
