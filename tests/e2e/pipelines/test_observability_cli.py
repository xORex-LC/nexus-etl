"""E2E-покрытие CLI-эргономики observability: maintenance/obs команды и latest pointers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from connector.common.observability import ObservabilityArtifactKind
from connector.config.loader import load_app_config
from connector.config.projections import to_cache_db_config
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.cache.dsl_runtime import load_cache_dsl_runtime
from connector.infra.cache.repository.cache_repository import SqliteCacheRepository
from connector.infra.sqlite.engine import open_sqlite
from connector.main import app
from tests.runtime_test_support import (
    active_log_path,
    latest_plan_path,
    latest_pointer_path,
    latest_report_path,
    ledger_index_path,
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


def test_obs_commands_use_ledger_and_latest_pointers(tmp_path: Path) -> None:
    cache_dir = tmp_path / "cache"
    initialize_test_vault(cache_dir)
    _seed_org(tmp_path, org_ouid=10)

    csv_path = tmp_path / "employees.csv"
    _write_csv(
        csv_path,
        [
            _make_row(
                raw_id="1001", full_name="Doe John M", contacts="+123456", org_id="10"
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

    plan_result = runner.invoke(
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
            "obs-cli-plan",
            "import",
            "plan",
        ],
        input=f"{TEST_UNSEAL_PASSPHRASE}\n",
    )

    assert plan_result.exit_code == 0

    report_path = latest_report_path(tmp_path / "reports", "import-plan")
    plan_path = latest_plan_path(tmp_path / "var" / "plans")
    log_path = active_log_path(tmp_path / "logs", "import-plan")

    report_pointer = latest_pointer_path(
        tmp_path / "reports",
        "import-plan",
        artifact=ObservabilityArtifactKind.REPORT,
    )
    plan_pointer = latest_pointer_path(
        tmp_path / "var" / "plans",
        "import-plan",
        artifact=ObservabilityArtifactKind.PLAN,
    )
    log_pointer = latest_pointer_path(
        tmp_path / "logs",
        "import-plan",
        artifact=ObservabilityArtifactKind.LOG,
    )

    assert report_pointer.exists()
    assert plan_pointer.exists()
    assert log_pointer.exists()
    assert report_pointer.read_text(encoding="utf-8") == report_path.read_text(
        encoding="utf-8"
    )
    assert plan_pointer.read_text(encoding="utf-8") == plan_path.read_text(
        encoding="utf-8"
    )
    assert log_pointer.read_text(encoding="utf-8") == log_path.read_text(
        encoding="utf-8"
    )

    latest_report = runner.invoke(
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
            "obs-latest-report",
            "obs",
            "latest",
            "planner",
        ],
    )
    assert latest_report.exit_code == 0
    assert str(report_path) in latest_report.stdout
    assert "SUCCESS" in latest_report.stdout

    latest_plan = runner.invoke(
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
            "obs-latest-plan",
            "obs",
            "latest",
            "planner",
            "--artifact",
            "plan",
        ],
    )
    assert latest_plan.exit_code == 0
    assert str(plan_path) in latest_plan.stdout
    assert '"run_id": "obs-cli-plan"' in latest_plan.stdout

    tail_log = runner.invoke(
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
            "obs-tail-log",
            "obs",
            "tail",
            "planner",
            "--lines",
            "5",
        ],
    )
    assert tail_log.exit_code == 0
    assert str(log_path) in tail_log.stdout
    assert "Plan written:" in tail_log.stdout or "Command started" in tail_log.stdout


def test_maintenance_prune_matches_runtime_retention_rules(tmp_path: Path) -> None:
    config_path = write_runtime_config(tmp_path)
    planner_logs = tmp_path / "var" / "logs" / "planner"
    planner_reports = tmp_path / "reports" / "planner"
    planner_plans = tmp_path / "var" / "plans" / "planner"
    for directory in (planner_logs, planner_reports, planner_plans):
        directory.mkdir(parents=True, exist_ok=True)

    old_log = planner_logs / "2026-01-01_planner.log"
    fresh_log = planner_logs / "2026-06-05_planner.log"
    old_report = planner_reports / "2026-01-01T01-00-00_planner.json"
    fresh_report = planner_reports / "2026-06-05T01-00-00_planner.json"
    old_plan = planner_plans / "2026-01-01T01-00-00_planner.json"
    fresh_plan = planner_plans / "2026-06-05T01-00-00_planner.json"
    for path in (old_log, fresh_log, old_report, fresh_report, old_plan, fresh_plan):
        path.write_text(path.name, encoding="utf-8")

    ledger_path = ledger_index_path(tmp_path / "var" / "logs", "import-plan")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "run_id": "old",
                        "pipeline_run_id": "old",
                        "component": "planner",
                        "started_at": "2026-01-01T01:00:00+00:00",
                        "finished_at": "2026-01-01T01:01:00+00:00",
                        "status": "SUCCESS",
                        "row_counters": {},
                        "log_path": str(old_log),
                        "report_path": str(old_report),
                        "plan_path": str(old_plan),
                    }
                ),
                json.dumps(
                    {
                        "run_id": "fresh",
                        "pipeline_run_id": "fresh",
                        "component": "planner",
                        "started_at": "2026-06-05T01:00:00+00:00",
                        "finished_at": "2026-06-05T01:01:00+00:00",
                        "status": "SUCCESS",
                        "row_counters": {},
                        "log_path": str(fresh_log),
                        "report_path": str(fresh_report),
                        "plan_path": str(fresh_plan),
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    marker_day = datetime.now(timezone.utc).date().isoformat()
    for marker_path in (
        planner_logs / ".retention.marker",
        planner_reports / ".report-retention.marker",
        planner_plans / ".plan-retention.marker",
        planner_logs / ".ledger-retention.marker",
    ):
        marker_path.write_text(marker_day, encoding="utf-8")

    prune_result = runner.invoke(
        app,
        [
            "--config",
            str(config_path),
            "--run-id",
            "maintenance-prune-run",
            "maintenance",
            "prune",
            "--component",
            "planner",
            "--force",
        ],
    )

    assert prune_result.exit_code == 0
    assert "planner: logs=1 reports=1 plans=1 ledger=1" in prune_result.stdout
    assert not old_log.exists()
    assert not old_report.exists()
    assert not old_plan.exists()
    assert fresh_log.exists()
    assert fresh_report.exists()
    assert fresh_plan.exists()
    ledger_payload = ledger_path.read_text(encoding="utf-8")
    assert '"run_id": "old"' not in ledger_payload
    assert '"run_id": "fresh"' in ledger_payload
