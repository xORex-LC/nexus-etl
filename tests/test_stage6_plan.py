import json
from pathlib import Path

from typer.testing import CliRunner

from connector.infra.cache.db import ensureSchema, getCacheDbPath, openCacheDb
from connector.infra.cache.repo import upsertOrganization, upsertUser
from connector.main import app

runner = CliRunner()

def _write_csv(path: Path, rows: list[list[str | None]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(";".join("" if v is None else str(v) for v in row) + "\n")

def _seed_org(conn, ouid: int) -> None:
    upsertOrganization(
        conn,
        {"_ouid": ouid, "code": f"ORG-{ouid}", "name": f"Org {ouid}", "parent_id": None, "updated_at": None},
    )
    conn.commit()

def _seed_user(conn, *, _id: str, match_key: str, phone: str, organization_id: int) -> None:
    upsertUser(
        conn,
        {
            "_id": _id,
            "_ouid": int(_id.replace("u", "")) if _id.startswith("u") else 1,
            "personnel_number": "100",
            "last_name": "Doe",
            "first_name": "John",
            "middle_name": "M",
            "match_key": match_key,
            "mail": "john@example.com",
            "user_name": "jdoe",
            "phone": phone,
            "usr_org_tab_num": "TAB-100",
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
    conn.commit()

def _run_plan(tmp_path: Path, csv_path: Path, run_id: str) -> tuple[int, Path]:
    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
    cache_dir = tmp_path / "cache"
    args = [
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
        "--csv",
        str(csv_path),
    ]
    result = runner.invoke(app, args)
    report_path = report_dir / f"report_import-plan_{run_id}.json"
    return result.exit_code, report_path

def test_plan_error_when_match_key_cannot_be_built(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    try:
        ensureSchema(conn)
        _seed_org(conn, ouid=10)
    finally:
        conn.close()

    csv_path = tmp_path / "input.csv"
    # personnelNumber missing -> match_key_missing
    _write_csv(
        csv_path,
        [
            [
                "user@example.com",
                "Doe",
                "John",
                "M",
                "true",
                "jdoe",
                "+111",
                "secret",
                "",  # personnelNumber
                "",
                "10",
                "Engineer",
                "",
                "TAB-100",
            ]
        ],
    )

    exit_code, report_path = _run_plan(tmp_path, csv_path, run_id="plan-missing")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["summary"]["failed"] == 1
    assert report["meta"]["plan_file"] is not None

def test_plan_create_when_not_found(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    try:
        ensureSchema(conn)
        _seed_org(conn, ouid=20)
    finally:
        conn.close()

    csv_path = tmp_path / "create.csv"
    _write_csv(
        csv_path,
        [
            [
                "user@example.com",
                "Doe",
                "John",
                "M",
                "false",
                "jdoe",
                "+111",
                "secret",
                "100",
                "",
                "20",
                "Engineer",
                "",
                "TAB-100",
            ]
        ],
    )

    exit_code, report_path = _run_plan(tmp_path, csv_path, run_id="plan-create")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["summary"]["planned_create"] == 1
    assert report["summary"]["failed"] == 0

def test_plan_update_when_found_and_diff(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    try:
        ensureSchema(conn)
        _seed_org(conn, ouid=30)
        _seed_user(conn, _id="u1", match_key="Doe|John|M|100", phone="+111", organization_id=30)
    finally:
        conn.close()

    csv_path = tmp_path / "update.csv"
    _write_csv(
        csv_path,
        [
            [
                "user@example.com",
                "Doe",
                "John",
                "M",
                "false",
                "jdoe",
                "+222",  # phone changed
                "secret",
                "100",
                "",
                "30",
                "Engineer",
                "",
                "TAB-100",
            ]
        ],
    )

    exit_code, report_path = _run_plan(tmp_path, csv_path, run_id="plan-update")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["summary"]["planned_update"] == 1
    assert report["summary"]["failed"] == 0

def test_plan_skip_when_no_diff(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    try:
        ensureSchema(conn)
        _seed_org(conn, ouid=40)
        _seed_user(conn, _id="u2", match_key="Doe|John|M|100", phone="+111", organization_id=40)
    finally:
        conn.close()

    csv_path = tmp_path / "skip.csv"
    _write_csv(
        csv_path,
        [
            [
                "john@example.com",
                "Doe",
                "John",
                "M",
                "false",
                "jdoe",
                "+111",
                "secret",
                "100",
                "",
                "40",
                "Engineer",
                "",
                "TAB-100",
            ]
        ],
    )

    exit_code, report_path = _run_plan(tmp_path, csv_path, run_id="plan-skip")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert report["summary"]["planned_update"] == 0
    assert report["summary"]["skipped"] == 1

def test_plan_conflict_when_multiple_same_match_key(monkeypatch, tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    try:
        ensureSchema(conn)
        _seed_org(conn, ouid=50)
    finally:
        conn.close()

    # Force duplicate candidates despite UNIQUE constraint by monkeypatching matcher
    import connector.domain.planning.adapters as planning_adapters
    from connector.domain.models import MatchResult, MatchStatus

    monkeypatch.setattr(
        planning_adapters.CacheEmployeeLookup,
        "match_by_key",
        lambda self, mk, include_deleted: MatchResult(
            status=MatchStatus.CONFLICT, candidate=None, candidates=[{"_id": "a"}, {"_id": "b"}]
        ),
    )

    csv_path = tmp_path / "conflict.csv"
    _write_csv(
        csv_path,
        [
            [
                "user@example.com",
                "Doe",
                "John",
                "M",
                "false",
                "jdoe",
                "+111",
                "secret",
                "100",
                "",
                "50",
                "Engineer",
                "",
                "TAB-100",
            ]
        ],
    )

    exit_code, report_path = _run_plan(tmp_path, csv_path, run_id="plan-conflict")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["summary"]["failed"] == 1

def test_plan_error_when_org_missing(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    try:
        ensureSchema(conn)
        # org intentionally not seeded
    finally:
        conn.close()

    csv_path = tmp_path / "org-missing.csv"
    _write_csv(
        csv_path,
        [
            [
                "user@example.com",
                "Doe",
                "John",
                "M",
                "false",
                "jdoe",
                "+111",
                "secret",
                "100",
                "",
                "999",
                "Engineer",
                "",
                "TAB-100",
            ]
        ],
    )

    exit_code, report_path = _run_plan(tmp_path, csv_path, run_id="plan-org-missing")
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["summary"]["failed"] == 1
