import json
from pathlib import Path

from typer.testing import CliRunner

from connector.config.loader import load_app_config
from connector.config.projections import to_cache_db_config, to_identity_db_config
from connector.infra.sqlite.engine import open_sqlite, SqliteEngine
from connector.infra.cache.dsl_runtime import load_cache_dsl_runtime
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.cache.repository.cache_repository import SqliteCacheRepository
from connector.infra.identity.sqlite.identity_repository import SqliteIdentityRepository
from connector.infra.identity.sqlite.schema import ensure_identity_schema
from connector.domain.transform.matcher.identity_keys import format_identity_key
from connector.main import app
from tests.runtime_test_support import (
    latest_plan_path,
    latest_report_path,
    prepare_tracked_employees_source_file,
    tracked_employees_runtime_roots,
    write_runtime_config,
)
from tests.vault_unseal_setup import TEST_UNSEAL_PASSPHRASE, initialize_test_vault

runner = CliRunner()

CSV_HEADER = (
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
)


def _write_csv(path: Path, rows: list[list[str | None]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write(";".join(CSV_HEADER) + "\n")
        for row in rows:
            f.write(";".join("" if v is None else str(v) for v in row) + "\n")


def _write_organizations_csv(path: Path, rows: list[dict[str, str | None]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        f.write("id;name;parent_id\n")
        for row in rows:
            f.write(
                ";".join(
                    "" if row.get(field) is None else str(row.get(field))
                    for field in ("id", "name", "parent_id")
                )
                + "\n"
            )


def _write_adjacency_topology_fixture() -> None:
    topology_path = (
        tracked_employees_runtime_roots()["datasets_root"]
        / "organizations"
        / "organizations.topology.yaml"
    )
    topology_path.write_text(
        """
dataset: organizations
topology:
  canonicalization:
    ops:
      - op: trim
      - op: lower
      - op: regex_replace
        pattern: '\\s+'
        repl: " "
      - op: compact
  source:
    mode: adjacency_list
    node_id_field: id
    parent_id_field: parent_id
    label_field: name
    target_membership_field: code
    on_unanchored: skip
  target:
    mode: adjacency_list
    node_id_field: _ouid
    parent_id_field: parent_id
    target_label_field: name
    payload_target_id_field: _id
""".lstrip(),
        encoding="utf-8",
    )


def _write_path_columns_topology_fixture() -> None:
    topology_path = (
        tracked_employees_runtime_roots()["datasets_root"]
        / "organizations"
        / "organizations.topology.yaml"
    )
    topology_path.write_text(
        """
dataset: organizations
topology:
  canonicalization:
    ops:
      - op: trim
      - op: lower
      - op: regex_replace
        pattern: '\\s+'
        repl: " "
      - op: compact
  source:
    mode: path_columns
    path_columns:
      - field: level_1_name
      - field: level_2_name
      - field: level_3_name
  target:
    mode: adjacency_list
    node_id_field: _ouid
    parent_id_field: parent_id
    target_label_field: name
    payload_target_id_field: _id
""".lstrip(),
        encoding="utf-8",
    )


def make_row(
    *,
    raw_id: str,
    full_name: str,
    login: str,
    email_or_phone: str,
    contacts: str,
    flags: str,
    role: str,
    org_id: str,
    tab: str,
    password: str = "secret",
    org: str = "Org=Engineering",
    manager: str = "",
) -> list[str | None]:
    _ = (login, email_or_phone, flags, password, org, manager, tab)
    organization_name = f"Org {org_id}"
    return [
        raw_id,
        full_name,
        organization_name,
        "",
        "",
        "",
        "",
        "",
        role,
        "",
        contacts,
        "",
        "",
        "",
        "",
    ]


def _build_repo(db_path: str) -> SqliteCacheRepository:
    engine = open_sqlite(to_cache_db_config(load_app_config().app_config), db_path)
    cache_specs = list(load_cache_dsl_runtime().cache_specs)
    ensure_cache_ready(engine, cache_specs)
    return SqliteCacheRepository(engine, cache_specs)


def _open_identity_engine(cache_db_path: str) -> SqliteEngine:
    identity_db_path = str(Path(cache_db_path).parent / "identity.sqlite3")
    engine = open_sqlite(
        to_identity_db_config(load_app_config().app_config), identity_db_path
    )
    ensure_identity_schema(engine)
    return engine


def _seed_org(repo: SqliteCacheRepository, ouid: int) -> None:
    identity_engine = _open_identity_engine(repo.engine.db_path)
    try:
        identity_repo = SqliteIdentityRepository(identity_engine)
        with repo.engine.transaction():
            repo.upsert(
                "organizations",
                {
                    "_id": str(ouid),
                    "_ouid": ouid,
                    "code": str(ouid),
                    "name": f"Org {ouid}",
                    "match_key": str(ouid),
                    "parent_id": None,
                    "updated_at": None,
                },
            )
        with identity_engine.transaction():
            identity_repo.upsert_identity(
                "organizations", format_identity_key("_ouid", str(ouid)), str(ouid)
            )
            identity_repo.upsert_identity(
                "organizations", format_identity_key("name", f"Org {ouid}"), str(ouid)
            )
            identity_repo.upsert_identity(
                "organizations", format_identity_key("code", str(ouid)), str(ouid)
            )
    finally:
        identity_engine.close()


def _seed_org_row(
    repo: SqliteCacheRepository,
    *,
    record_id: str,
    ouid: int,
    code: str,
    name: str,
    parent_id: int | None,
) -> None:
    identity_engine = _open_identity_engine(repo.engine.db_path)
    try:
        identity_repo = SqliteIdentityRepository(identity_engine)
        with repo.engine.transaction():
            repo.upsert(
                "organizations",
                {
                    "_id": record_id,
                    "_ouid": ouid,
                    "code": code,
                    "name": name,
                    "match_key": code,
                    "parent_id": parent_id,
                    "updated_at": "2026-06-01T00:00:00+00:00",
                },
            )
            repo.set_meta("organizations", "cache_snapshot_revision", "rev-topology")
            repo.set_meta(
                "organizations",
                "last_refresh_at",
                "2026-06-01T00:30:00+00:00",
            )
        with identity_engine.transaction():
            identity_repo.upsert_identity(
                "organizations",
                format_identity_key("_ouid", str(ouid)),
                str(ouid),
            )
            identity_repo.upsert_identity(
                "organizations",
                format_identity_key("name", name),
                str(ouid),
            )
            identity_repo.upsert_identity(
                "organizations",
                format_identity_key("code", code),
                str(ouid),
            )
    finally:
        identity_engine.close()


def _seed_user(
    repo: SqliteCacheRepository,
    *,
    _id: str,
    match_key: str,
    phone: str,
    organization_id: int,
) -> None:
    identity_engine = _open_identity_engine(repo.engine.db_path)
    try:
        identity_repo = SqliteIdentityRepository(identity_engine)
        ouid = int(_id.replace("u", "")) if _id.startswith("u") else 1
        with repo.engine.transaction():
            repo.upsert(
                "employees",
                {
                    "_id": _id,
                    "_ouid": ouid,
                    "personnel_number": "100",
                    "last_name": "Doe",
                    "first_name": "John",
                    "middle_name": "M",
                    "match_key": match_key,
                    "mail": "john@example.com",
                    "user_name": "DOE",
                    "phone": phone,
                    "usr_org_tab_num": "461462",
                    "organization_id": organization_id,
                    "account_status": "active",
                    "deletion_date": None,
                    "_rev": None,
                    "manager_ouid": None,
                    "is_logon_disabled": False,
                    "position": "Engineer",
                    "updated_at": None,
                },
            )
        with identity_engine.transaction():
            identity_repo.upsert_identity(
                "employees", format_identity_key("match_key", match_key), str(ouid)
            )
            identity_repo.upsert_identity(
                "employees",
                format_identity_key("organization_id", str(organization_id)),
                str(ouid),
            )
    finally:
        identity_engine.close()


def _run_plan(
    tmp_path: Path,
    csv_path: Path,
    run_id: str,
    *,
    dataset: str | None = None,
    source_filename: str | None = None,
) -> tuple[int, Path]:
    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
    cache_dir = tmp_path / "cache"
    initialize_test_vault(cache_dir)
    if source_filename is None:
        runtime_csv_path = prepare_tracked_employees_source_file(csv_path)
    else:
        runtime_csv_path = csv_path.parent / source_filename
        if csv_path.resolve() != runtime_csv_path.resolve():
            runtime_csv_path.write_text(
                csv_path.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
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
    args = [
        "--config",
        str(config_path),
        "--log-dir",
        str(log_dir),
        "--report-dir",
        str(report_dir),
        "--cache-dir",
        str(cache_dir),
        "--run-id",
        run_id,
        "import",
        "plan",
    ]
    if dataset is not None:
        args.extend(["--dataset", dataset])
    result = runner.invoke(app, args, input=f"{TEST_UNSEAL_PASSPHRASE}\n")
    plan_path = latest_plan_path(tmp_path / "var" / "plans", required=False)
    if plan_path is None:
        plan_path = tmp_path / "var" / "plans" / "planner" / "__missing__.json"
    return result.exit_code, plan_path


def test_plan_error_when_match_key_cannot_be_built(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = str(Path(cache_dir) / "ankey_cache.sqlite3")
    repo = _build_repo(db_path)
    _seed_org(repo, ouid=10)

    csv_path = tmp_path / "input.csv"
    # personnelNumber missing -> match_key_missing
    _write_csv(
        csv_path,
        [
            make_row(
                raw_id="",
                full_name="Doe John M",
                login="jdoe",
                email_or_phone="user@example.com",
                contacts="+111111",
                flags="disabled=true",
                role="Engineer",
                org_id="10",
                tab="TAB-100",
            )
        ],
    )

    exit_code, plan_path = _run_plan(tmp_path, csv_path, run_id="plan-missing")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert plan["summary"]["planned_create"] == 0
    assert plan["summary"]["planned_update"] == 0
    assert plan["summary"]["skipped"] == 0
    assert plan["items"] == []


def test_plan_create_when_not_found(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = str(Path(cache_dir) / "ankey_cache.sqlite3")
    repo = _build_repo(db_path)
    _seed_org(repo, ouid=20)

    csv_path = tmp_path / "create.csv"
    _write_csv(
        csv_path,
        [
            make_row(
                raw_id="100",
                full_name="Doe John M",
                login="jdoe",
                email_or_phone="user@example.com",
                contacts="+111111",
                flags="disabled=false",
                role="Engineer",
                org_id="20",
                tab="TAB-100",
            )
        ],
    )

    exit_code, plan_path = _run_plan(tmp_path, csv_path, run_id="plan-create")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert plan["summary"]["planned_create"] == 1
    assert plan["summary"]["planned_update"] == 0
    assert len(plan["items"]) == 1
    assert plan["items"][0]["op"] == "create"


def test_plan_update_when_found_and_diff(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = str(Path(cache_dir) / "ankey_cache.sqlite3")
    repo = _build_repo(db_path)
    _seed_org(repo, ouid=30)
    _seed_user(
        repo, _id="u1", match_key="Doe|John|M|100", phone="+111111", organization_id=30
    )

    csv_path = tmp_path / "update.csv"
    _write_csv(
        csv_path,
        [
            make_row(
                raw_id="100",
                full_name="Doe John M",
                login="jdoe",
                email_or_phone="user@example.com",
                contacts="+222222",
                flags="disabled=false",
                role="Engineer",
                org_id="30",
                tab="TAB-100",
            )
        ],
    )

    exit_code, plan_path = _run_plan(tmp_path, csv_path, run_id="plan-update")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert plan["summary"]["planned_update"] == 1
    assert len(plan["items"]) == 1
    assert plan["items"][0]["op"] == "update"
    assert "phone" in plan["items"][0]["changes"]


def test_plan_update_when_existing_mail_conflicts_with_source2_null_email(
    tmp_path: Path,
):
    cache_dir = tmp_path / "cache"
    db_path = str(Path(cache_dir) / "ankey_cache.sqlite3")
    repo = _build_repo(db_path)
    _seed_org(repo, ouid=40)
    _seed_user(
        repo, _id="u2", match_key="Doe|John|M|100", phone="+111111", organization_id=40
    )

    csv_path = tmp_path / "skip.csv"
    _write_csv(
        csv_path,
        [
            make_row(
                raw_id="100",
                full_name="Doe John M",
                login="jdoe",
                email_or_phone="john@example.com",
                contacts="+111111",
                flags="disabled=false",
                role="Engineer",
                org_id="40",
                tab="TAB-100",
            )
        ],
    )

    exit_code, plan_path = _run_plan(tmp_path, csv_path, run_id="plan-skip")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert plan["summary"]["planned_update"] == 0
    assert plan["summary"]["skipped"] == 1
    assert plan["items"] == []


def test_plan_conflict_when_multiple_same_match_key(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = str(Path(cache_dir) / "ankey_cache.sqlite3")
    repo = _build_repo(db_path)
    _seed_org(repo, ouid=50)

    csv_path = tmp_path / "conflict.csv"
    _write_csv(
        csv_path,
        [
            make_row(
                raw_id="100",
                full_name="Doe John M",
                login="jdoe",
                email_or_phone="user@example.com",
                contacts="+111111",
                flags="disabled=false",
                role="Engineer",
                org_id="50",
                tab="TAB-100",
            )
        ]
        + [
            make_row(
                raw_id="100",
                full_name="Doe John M",
                login="jdoe",
                email_or_phone="another@example.com",
                contacts="+333333",
                flags="disabled=false",
                role="Engineer",
                org_id="50",
                tab="TAB-100",
            )
        ],
    )

    exit_code, plan_path = _run_plan(tmp_path, csv_path, run_id="plan-conflict")
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert plan["summary"]["planned_create"] == 1
    assert len(plan["items"]) == 1


def test_plan_error_when_org_missing(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = str(Path(cache_dir) / "ankey_cache.sqlite3")
    _build_repo(db_path)
    # org intentionally not seeded

    csv_path = tmp_path / "org-missing.csv"
    _write_csv(
        csv_path,
        [
            make_row(
                raw_id="100",
                full_name="Doe John M",
                login="jdoe",
                email_or_phone="user@example.com",
                contacts="+111111",
                flags="disabled=false",
                role="Engineer",
                org_id="999",
                tab="TAB-100",
            )
        ],
    )

    exit_code, plan_path = _run_plan(tmp_path, csv_path, run_id="plan-org-missing")
    assert exit_code != 0
    assert plan_path.exists() is False


def test_plan_resolve_topology_propagates_organization_fk_into_plan(tmp_path: Path):
    _write_path_columns_topology_fixture()
    cache_dir = tmp_path / "cache"
    db_path = str(Path(cache_dir) / "ankey_cache.sqlite3")
    repo = _build_repo(db_path)
    _seed_org_row(
        repo,
        record_id="org-root",
        ouid=10,
        code="10",
        name="Head Office",
        parent_id=None,
    )
    _seed_org_row(
        repo,
        record_id="org-branch-a",
        ouid=20,
        code="20",
        name="Branch A",
        parent_id=10,
    )
    _seed_org_row(
        repo,
        record_id="org-branch-b",
        ouid=30,
        code="30",
        name="Branch B",
        parent_id=10,
    )
    _seed_org_row(
        repo,
        record_id="org-a",
        ouid=100,
        code="A-100",
        name="Shared Team",
        parent_id=20,
    )
    _seed_org_row(
        repo,
        record_id="org-b",
        ouid=200,
        code="B-200",
        name="Shared Team",
        parent_id=30,
    )

    csv_path = tmp_path / "topology-resolve.csv"
    _write_csv(
        csv_path,
        [
            [
                "100",
                "Doe John M",
                "Head Office",
                "Branch A",
                "Shared Team",
                "",
                "",
                "Shared Team",
                "Engineer",
                "",
                "+111111",
                "",
                "",
                "",
                "",
            ]
        ],
    )

    exit_code, plan_path = _run_plan(
        tmp_path,
        csv_path,
        run_id="plan-topology-resolve",
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert plan["summary"]["planned_create"] == 1
    assert len(plan["items"]) == 1
    assert plan["items"][0]["desired_state"]["organization_id"] == 100


def test_plan_filters_unanchored_organization_subtree(tmp_path: Path):
    _write_adjacency_topology_fixture()
    cache_dir = tmp_path / "cache"
    db_path = str(Path(cache_dir) / "ankey_cache.sqlite3")
    repo = _build_repo(db_path)
    _seed_org_row(
        repo,
        record_id="org-root",
        ouid=100,
        code="100",
        name="Existing root",
        parent_id=None,
    )

    csv_path = tmp_path / "organizations.csv"
    _write_organizations_csv(
        csv_path,
        [
            {"id": "100", "name": "Existing root", "parent_id": None},
            {"id": "382", "name": "Service", "parent_id": "378"},
            {"id": "383", "name": "Subservice", "parent_id": "382"},
        ],
    )

    exit_code, plan_path = _run_plan(
        tmp_path,
        csv_path,
        run_id="plan-org-anchoring",
        dataset="organizations",
        source_filename="source_departments.csv",
    )
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    report = json.loads(
        latest_report_path(tmp_path / "reports", "import-plan").read_text(
            encoding="utf-8"
        )
    )

    assert exit_code == 0
    assert plan["summary"]["failed_rows"] == 2
    assert report["context"]["topology"]["source_validation"]["dropped"] == 2
    failed_codes = [
        diagnostic["code"]
        for item in report["items"]
        for diagnostic in item["diagnostics"]
        if item["status"] == "FAILED"
    ]
    assert failed_codes == [
        "TOPOLOGY_SOURCE_UNANCHORED",
        "TOPOLOGY_SOURCE_UNANCHORED",
    ]
