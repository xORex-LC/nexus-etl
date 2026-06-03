"""
Сквозные интеграционные тесты vault-контура: import plan -> import apply.

Проверяем, что pipeline в vault-режиме проходит оба сценария:
- create flow (нет записи в cache -> planned_create -> apply create);
- update flow (есть existing в cache -> planned_update -> apply update).
"""

from __future__ import annotations

from connector.config.models import AppConfig
from connector.config.projections import to_cache_db_config, to_identity_db_config
import json
from pathlib import Path

from typer.testing import CliRunner

from connector.domain.transform.matcher.identity_keys import format_identity_key
from connector.infra.sqlite.engine import open_sqlite
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.cache.dsl_runtime import load_cache_dsl_runtime
from connector.infra.cache.repository.cache_repository import SqliteCacheRepository
from connector.infra.identity.sqlite.identity_repository import SqliteIdentityRepository
from connector.infra.identity.sqlite.schema import ensure_identity_schema
from connector.main import app
from tests.runtime_test_support import (
    prepare_tracked_employees_source_file,
    tracked_employees_runtime_roots,
    write_runtime_config,
)
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


def _write_minimal_employees_csv(
    path: Path,
    *,
    phone: str,
    password: str,
) -> None:
    _ = password
    row = [
        "1001",
        "Doe John M",
        "Org 10",
        "",
        "",
        "",
        "",
        "",
        "Engineer",
        "",
        phone,
        "",
        "",
        "",
        "",
    ]
    path.write_text("\n".join([HEADER, ";".join(row)]), encoding="utf-8")


def _run_import_plan(
    *,
    tmp_path: Path,
    run_id: str,
    csv_path: Path,
):
    cache_dir = tmp_path / "cache"
    initialize_test_vault(cache_dir)
    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
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
            "--cache-dir",
            str(cache_dir),
            "--log-dir",
            str(log_dir),
            "--report-dir",
            str(report_dir),
            "--run-id",
            run_id,
            "import",
            "plan",
        ],
        input=f"{TEST_UNSEAL_PASSPHRASE}\n",
    )
    return result, report_dir / f"plan_import_{run_id}.json"


def _run_import_apply(
    *,
    tmp_path: Path,
    run_id: str,
    plan_path: Path,
):
    cache_dir = tmp_path / "cache"
    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
    roots = tracked_employees_runtime_roots()
    config_path = write_runtime_config(
        tmp_path,
        registry_path=roots["registry_path"],
        datasets_root=roots["datasets_root"],
        source_data_root=tmp_path,
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
            "--cache-dir",
            str(cache_dir),
            "--log-dir",
            str(log_dir),
            "--report-dir",
            str(report_dir),
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
        input=f"{TEST_UNSEAL_PASSPHRASE}\n",
    )
    return result, report_dir / f"report_import-apply_{run_id}.json"


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _extract_first_match_key(plan_payload: dict) -> str:
    items = plan_payload.get("items")
    if not isinstance(items, list) or not items:
        raise AssertionError("Plan must contain at least one item")
    source_ref = items[0].get("source_ref") if isinstance(items[0], dict) else None
    if not isinstance(source_ref, dict):
        raise AssertionError("Plan item source_ref is missing")
    match_key = source_ref.get("match_key")
    if not isinstance(match_key, str) or not match_key:
        raise AssertionError("Plan item source_ref.match_key is missing")
    return match_key


def _seed_existing_user_for_update(
    *,
    cache_dir: Path,
    match_key: str,
    phone: str = "+000000",
) -> None:
    """
    Записать existing user в cache, чтобы resolve классифицировал строку как update.
    """
    personnel_number = match_key.split("|")[-1]
    db_path = str(Path(cache_dir) / "ankey_cache.sqlite3")
    engine = open_sqlite(to_cache_db_config(AppConfig()), db_path)
    try:
        cache_specs = list(load_cache_dsl_runtime().cache_specs)
        ensure_cache_ready(engine, cache_specs)
        repo = SqliteCacheRepository(engine, cache_specs)
        with engine.transaction():
            repo.upsert(
                "employees",
                {
                    "_id": "existing-user-1001",
                    "_ouid": 1001,
                    "personnel_number": personnel_number,
                    "last_name": "Doe",
                    "first_name": "John",
                    "middle_name": "M",
                    "match_key": match_key,
                    "mail": "john.doe@example.com",
                    "user_name": "jdoe",
                    "phone": phone,
                    "usr_org_tab_num": "TAB-5001",
                    "organization_id": 10,
                    "account_status": "active",
                    "deletion_date": None,
                    "_rev": None,
                    "manager_ouid": None,
                    "is_logon_disabled": False,
                    "position": "Engineer",
                    "updated_at": "2026-02-18T10:00:00Z",
                },
            )
    finally:
        engine.close()


def _seed_organization_identities(
    *,
    cache_dir: Path,
    resolved_org_id: int = 10,
) -> None:
    """
    Добавить identity-index записи для organization link-resolve в employees resolve flow.
    """
    value = str(resolved_org_id)
    organization_name = f"Org {resolved_org_id}"
    identity_db_path = str(Path(cache_dir) / "identity.sqlite3")
    engine = open_sqlite(to_identity_db_config(AppConfig()), identity_db_path)
    try:
        ensure_identity_schema(engine)
        identity_repo = SqliteIdentityRepository(engine)
        with engine.transaction():
            identity_repo.upsert_identity("organizations", format_identity_key("_ouid", value), value)
            identity_repo.upsert_identity("organizations", format_identity_key("name", organization_name), value)
    finally:
        engine.close()

    # Stage F: import-plan активирует topology-bootstrap (employees.resolve.topology_link),
    # который строит target topology из org cache-таблицы. Без хотя бы одной org-строки
    # snapshot пуст → TOPOLOGY_TARGET_EMPTY и команда падает на bootstrap. Сеем одну
    # org-строку, чтобы target был непустым; FK по-прежнему резолвится по identity-index
    # (1 кандидат → topology refinement не срабатывает).
    cache_db_path = str(Path(cache_dir) / "ankey_cache.sqlite3")
    cache_engine = open_sqlite(to_cache_db_config(AppConfig()), cache_db_path)
    try:
        cache_specs = list(load_cache_dsl_runtime().cache_specs)
        ensure_cache_ready(cache_engine, cache_specs)
        cache_repo = SqliteCacheRepository(cache_engine, cache_specs)
        with cache_engine.transaction():
            cache_repo.upsert(
                "organizations",
                {
                    "_id": f"org-{value}",
                    "_ouid": resolved_org_id,
                    "code": value,
                    "name": organization_name,
                    "match_key": value,
                    "parent_id": None,
                    "updated_at": "2026-02-18T10:00:00Z",
                },
            )
            cache_repo.set_meta("organizations", "cache_snapshot_revision", "vault-flow-rev")
    finally:
        cache_engine.close()


def test_vault_full_pipeline_create_flow(tmp_path: Path):
    csv_path = tmp_path / "employees-create.csv"
    _write_minimal_employees_csv(csv_path, phone="+123456", password="SECRET_CREATE")
    _seed_organization_identities(cache_dir=tmp_path / "cache", resolved_org_id=10)

    plan_result, plan_path = _run_import_plan(
        tmp_path=tmp_path,
        run_id="vault-flow-create-plan",
        csv_path=csv_path,
    )
    assert plan_result.exit_code == 0
    assert plan_path.exists()

    plan_payload = _read_json(plan_path)
    assert int(plan_payload["summary"]["planned_create"]) >= 1
    assert any("password" in (item.get("secret_fields") or []) for item in plan_payload["items"])

    apply_result, apply_report_path = _run_import_apply(
        tmp_path=tmp_path,
        run_id="vault-flow-create-apply",
        plan_path=plan_path,
    )
    assert apply_result.exit_code == 0
    assert apply_report_path.exists()

    apply_report = _read_json(apply_report_path)
    assert int(apply_report["summary"]["ops"]["create"]["ok"]) >= 1
    assert int(apply_report["summary"]["rows_blocked"]) == 0


def test_vault_full_pipeline_update_flow(tmp_path: Path):
    csv_path = tmp_path / "employees-update.csv"
    _write_minimal_employees_csv(csv_path, phone="+123456", password="SECRET_UPDATE")
    _seed_organization_identities(cache_dir=tmp_path / "cache", resolved_org_id=10)

    probe_result, probe_plan_path = _run_import_plan(
        tmp_path=tmp_path,
        run_id="vault-flow-update-probe",
        csv_path=csv_path,
    )
    assert probe_result.exit_code == 0
    probe_plan = _read_json(probe_plan_path)
    match_key = _extract_first_match_key(probe_plan)

    _seed_existing_user_for_update(cache_dir=tmp_path / "cache", match_key=match_key, phone="+000000")

    plan_result, plan_path = _run_import_plan(
        tmp_path=tmp_path,
        run_id="vault-flow-update-plan",
        csv_path=csv_path,
    )
    assert plan_result.exit_code == 0
    assert plan_path.exists()

    plan_payload = _read_json(plan_path)
    assert int(plan_payload["summary"]["planned_update"]) >= 1
    assert any(item.get("op") == "update" for item in plan_payload["items"])

    apply_result, apply_report_path = _run_import_apply(
        tmp_path=tmp_path,
        run_id="vault-flow-update-apply",
        plan_path=plan_path,
    )
    assert apply_result.exit_code == 0
    assert apply_report_path.exists()

    apply_report = _read_json(apply_report_path)
    assert int(apply_report["summary"]["ops"]["update"]["ok"]) >= 1
    assert int(apply_report["summary"]["rows_blocked"]) == 0
