import json
from pathlib import Path

from typer.testing import CliRunner

from connector.cacheDb import ensureSchema, getCacheDbPath, openCacheDb
from connector.cacheRepo import getCounts, getUserByMatchKey, upsertUser
from connector.cli import app

runner = CliRunner()

DATA_DIR = Path(__file__).parent / "data"
USERS_JSON = DATA_DIR / "users_min.json"
ORG_JSON = DATA_DIR / "org_min.json"

def test_cache_schema_created(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    try:
        ensureSchema(conn)
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert {"meta", "users", "organizations"}.issubset(tables)
        schema_version = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        assert schema_version == "2"
    finally:
        conn.close()

    assert db_path.exists()

def test_cache_upsert_user(tmp_path: Path):
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    try:
        ensureSchema(conn)
        user = {
            "_id": "user-123",
            "_ouid": 999,
            "personnel_number": "7777",
            "last_name": "Doe",
            "first_name": "John",
            "middle_name": "M",
            "match_key": "Doe|John|M|7777",
            "mail": "john.doe@example.com",
            "user_name": "jdoe",
            "phone": "+111",
            "usr_org_tab_num": "TAB-7777",
            "organization_id": 201,
            "account_status": "active",
            "deletion_date": None,
            "_rev": None,
            "manager_ouid": None,
            "is_logon_disabled": False,
            "position": "Engineer",
            "updated_at": "2024-01-01T00:00:00Z",
        }
        status1 = upsertUser(conn, user)
        user["phone"] = "+222"
        status2 = upsertUser(conn, user)
        fetched = getUserByMatchKey(conn, user["match_key"])
    finally:
        conn.close()

    assert status1 == "inserted"
    assert status2 == "updated"
    assert fetched is not None
    assert fetched["phone"] == "+222"

def run_cache_refresh(tmp_path: Path, run_id: str = "refresh-1", users_json: Path | None = USERS_JSON, org_json: Path | None = ORG_JSON):
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
        "cache",
        "refresh",
    ]
    if users_json:
        args.extend(["--users-json", str(users_json)])
    if org_json:
        args.extend(["--org-json", str(org_json)])

    result = runner.invoke(app, args)
    report_path = report_dir / f"report_cache-refresh_{run_id}.json"
    return result, cache_dir, report_path, log_dir

def test_cache_refresh_from_json_creates_db_and_counts(tmp_path: Path):
    result, cache_dir, report_path, _ = run_cache_refresh(tmp_path, run_id="refresh-ok")

    assert result.exit_code == 0
    assert report_path.exists()

    db_path = Path(getCacheDbPath(cache_dir))
    assert db_path.exists()

    conn = openCacheDb(str(db_path))
    try:
        users_count, org_count = getCounts(conn)
    finally:
        conn.close()

    assert users_count == 1
    assert org_count == 1

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["created"] == 2  # 1 user + 1 org
    assert report["summary"]["failed"] == 0

def test_cache_status_ok(tmp_path: Path):
    refresh_result, cache_dir, _, _ = run_cache_refresh(tmp_path, run_id="refresh-for-status")
    assert refresh_result.exit_code == 0

    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
    result = runner.invoke(
        app,
        [
            "--log-dir",
            str(log_dir),
            "--report-dir",
            str(report_dir),
            "--cache-dir",
            str(cache_dir),
            "--run-id",
            "status-1",
            "cache",
            "status",
        ],
    )
    report_path = report_dir / "report_cache-status_status-1.json"

    assert result.exit_code == 0
    assert "users=1" in result.stdout
    assert "orgs=1" in result.stdout
    assert report_path.exists()

def test_cache_clear_empties_tables(tmp_path: Path):
    refresh_result, cache_dir, _, _ = run_cache_refresh(tmp_path, run_id="refresh-before-clear")
    assert refresh_result.exit_code == 0

    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
    result = runner.invoke(
        app,
        [
            "--log-dir",
            str(log_dir),
            "--report-dir",
            str(report_dir),
            "--cache-dir",
            str(cache_dir),
            "--run-id",
            "clear-1",
            "cache",
            "clear",
        ],
    )
    assert result.exit_code == 0

    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    try:
        users_count, org_count = getCounts(conn)
    finally:
        conn.close()

    assert users_count == 0
    assert org_count == 0

def test_cache_does_not_store_passwords(tmp_path: Path):
    secret = "TOP_SECRET"
    run_id = "no-secret"
    result, cache_dir, report_path, log_dir = run_cache_refresh(tmp_path, run_id=run_id)
    assert result.exit_code == 0

    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(users)")]
    finally:
        conn.close()

    assert "password" not in columns
    assert secret not in report_path.read_text(encoding="utf-8")

    log_path = log_dir / f"cache-refresh_{run_id}.log"
    assert log_path.exists()
    assert secret not in log_path.read_text(encoding="utf-8")
