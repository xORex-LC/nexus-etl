"""E2E-проверки run ledger на реальном CLI orchestration path."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from connector.config.loader import load_app_config
from connector.config.projections import to_cache_db_config
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.cache.dsl_runtime import load_cache_dsl_runtime
from connector.infra.cache.repository.cache_repository import SqliteCacheRepository
from connector.infra.sqlite.engine import open_sqlite
from connector.main import app
from tests.runtime_test_support import (
    ledger_index_path,
    latest_plan_path,
    latest_report_path,
    prepare_tracked_employees_source_file,
    tracked_employees_runtime_roots,
    write_runtime_config,
)
from tests.vault_unseal_setup import TEST_UNSEAL_PASSPHRASE, initialize_test_vault

pytestmark = pytest.mark.e2e

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


def _tracked_runtime_config(tmp_path: Path) -> Path:
    roots = tracked_employees_runtime_roots()
    return write_runtime_config(
        tmp_path,
        registry_path=roots["registry_path"],
        datasets_root=roots["datasets_root"],
        source_data_root=roots["source_data_root"],
        source_projection_root=roots["source_projection_root"],
        target_projection_root=roots["target_projection_root"],
        dictionary_specs_root=roots["dictionary_specs_root"],
        dictionary_data_root=roots["dictionary_data_root"],
    )


def _build_repo(db_path: str) -> SqliteCacheRepository:
    engine = open_sqlite(to_cache_db_config(load_app_config().app_config), db_path)
    cache_specs = list(load_cache_dsl_runtime().cache_specs)
    ensure_cache_ready(engine, cache_specs)
    return SqliteCacheRepository(engine, cache_specs)


def _seed_org(tmp_path: Path, org_ouid: int) -> None:
    cache_dir = tmp_path / "cache"
    db_path = str(cache_dir / "ankey_cache.sqlite3")
    repo = _build_repo(db_path)
    with repo.engine.transaction():
        repo.upsert(
            "organizations",
            {
                "_id": str(org_ouid),
                "_ouid": org_ouid,
                "code": str(org_ouid),
                "name": f"Org {org_ouid}",
                "match_key": str(org_ouid),
                "parent_id": None,
                "updated_at": None,
            },
        )


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    path.write_text(
        "\n".join([HEADER, *(";".join(row) for row in rows)]), encoding="utf-8"
    )


def _make_row(*, raw_id: str, full_name: str, contacts: str, org_id: str) -> list[str]:
    return [
        raw_id,
        full_name,
        "",
        "",
        "",
        "",
        "",
        f"Org {org_id}",
        "Engineer",
        "",
        contacts,
        "",
        "",
        "",
        "",
    ]


def _read_jsonl_payloads(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_import_plan_writes_ledger_entry_with_artifact_paths(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    initialize_test_vault(cache_dir)
    _seed_org(tmp_path, org_ouid=10)

    csv_path = tmp_path / "employees.csv"
    _write_csv(
        csv_path,
        [
            _make_row(
                raw_id="1001",
                full_name="Doe John M",
                contacts="+123456",
                org_id="10",
            )
        ],
    )
    runtime_csv_path = prepare_tracked_employees_source_file(csv_path)
    roots = tracked_employees_runtime_roots()
    config_path = write_runtime_config(
        tmp_path,
        registry_path=roots["registry_path"],
        datasets_root=roots["datasets_root"],
        source_data_root=runtime_csv_path.parent,
        source_projection_root=roots["source_projection_root"],
        target_projection_root=roots["target_projection_root"],
        dictionary_specs_root=roots["dictionary_specs_root"],
        dictionary_data_root=roots["dictionary_data_root"],
    )

    result = runner.invoke(
        app,
        [
            "--config",
            str(config_path),
            "--log-dir",
            str(tmp_path / "logs"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--cache-dir",
            str(cache_dir),
            "--run-id",
            "ledger-plan",
            "import",
            "plan",
        ],
        input=f"{TEST_UNSEAL_PASSPHRASE}\n",
    )

    assert result.exit_code == 0
    report_path = latest_report_path(tmp_path / "reports", "import-plan")
    plan_path = latest_plan_path(tmp_path / "var" / "plans")
    ledger_path = ledger_index_path(tmp_path / "logs", "import-plan")
    payloads = _read_jsonl_payloads(ledger_path)

    assert len(payloads) == 1
    assert payloads[0]["run_id"] == "ledger-plan"
    assert payloads[0]["component"] == "planner"
    assert payloads[0]["status"] == "SUCCESS"
    assert payloads[0]["report_path"] == str(report_path)
    assert payloads[0]["plan_path"] == str(plan_path)
    assert Path(payloads[0]["log_path"]).exists()


def test_import_apply_writes_ledger_entry_with_consumed_plan_path(
    tmp_path: Path,
) -> None:
    plan_path = tmp_path / "input-plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "meta": {
                    "run_id": "plan-source",
                    "generated_at": "2026-06-05T12:00:00+00:00",
                    "csv_path": "employees.csv",
                    "dataset": "employees",
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
                        "row_id": "line:1",
                        "line_no": 1,
                        "op": "create",
                        "target_id": "id-1",
                        "desired_state": {
                            "email": "u@example.com",
                            "last_name": "Doe",
                            "first_name": "John",
                            "middle_name": "M",
                            "is_logon_disable": False,
                            "user_name": "jdoe",
                            "phone": "+123456",
                            "password": "secret",
                            "personnel_number": "1001",
                            "manager_id": None,
                            "organization_id": 10,
                            "position": "Engineer",
                            "usr_org_tab_num": "TAB-1",
                        },
                        "changes": {},
                        "source_ref": {"match_key": "A|B|C|1"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "--config",
            str(_tracked_runtime_config(tmp_path)),
            "--log-dir",
            str(tmp_path / "logs"),
            "--report-dir",
            str(tmp_path / "reports"),
            "--cache-dir",
            str(tmp_path / "cache"),
            "--host",
            "api.local",
            "--port",
            "443",
            "--api-username",
            "user",
            "--api-password",
            "secret",
            "--run-id",
            "ledger-apply",
            "import",
            "apply",
            "--plan",
            str(plan_path),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    report_path = latest_report_path(tmp_path / "reports", "import-apply")
    ledger_path = ledger_index_path(tmp_path / "logs", "import-apply")
    payloads = _read_jsonl_payloads(ledger_path)

    assert len(payloads) == 1
    assert payloads[0]["run_id"] == "ledger-apply"
    assert payloads[0]["component"] == "applier"
    assert payloads[0]["status"] == "SUCCESS"
    assert payloads[0]["plan_path"] == str(plan_path)
    assert payloads[0]["report_path"] == str(report_path)
    assert Path(payloads[0]["log_path"]).exists()
