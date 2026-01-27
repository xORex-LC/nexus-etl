import json
from pathlib import Path

from typer.testing import CliRunner

from connector.infra.cache.db import getCacheDbPath, openCacheDb
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.cache.handlers.registry import CacheHandlerRegistry
from connector.infra.cache.handlers.generic_handler import GenericCacheHandler
from connector.datasets.cache_registry import list_cache_specs
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.repository import SqliteCacheRepository

from connector.main import app

runner = CliRunner()

HEADER = "raw_id,full_name,login,email_or_phone,contacts,org,manager,flags,employment,extra"


def write_csv(path: Path, rows: list[list[str]], include_header: bool = True) -> None:
    lines = []
    if include_header:
        lines.append(HEADER)
    for row in rows:
        lines.append(",".join(row))
    path.write_text("\n".join(lines), encoding="utf-8")


def run_validate(tmp_path: Path, csv_path: Path, run_id: str = "run-1", env: dict[str, str] | None = None):
    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
    cache_dir = tmp_path / "cache"
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
            run_id,
            "validate",
            "--csv",
            str(csv_path),
            "--csv-has-header",
        ],
        env=env,
    )
    report_path = report_dir / f"report_validate_{run_id}.json"
    return result, report_path


def _build_repo(conn) -> SqliteCacheRepository:
    engine = SqliteEngine(conn)
    registry = CacheHandlerRegistry()
    for spec in list_cache_specs():
        registry.register(GenericCacheHandler(spec))
    ensure_cache_ready(engine, registry)
    return SqliteCacheRepository(engine, registry)


def _seed_org(tmp_path: Path, org_ouid: int) -> None:
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    try:
        repo = _build_repo(conn)
        with repo.transaction():
            repo.upsert(
                "organizations",
                {"_ouid": org_ouid, "code": f"ORG-{org_ouid}", "name": f"Org {org_ouid}", "parent_id": None, "updated_at": None},
            )
    finally:
        conn.close()


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
    password: str = "SECRET1",
    org: str = "Org=Engineering",
    manager: str = "",
) -> list[str]:
    extra = f"password={password};org_id={org_id};tab={tab}"
    employment = f"role={role}"
    return [
        raw_id,
        full_name,
        login,
        email_or_phone,
        contacts,
        org,
        manager,
        flags,
        employment,
        extra,
    ]


def test_validate_ok_returns_0(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        make_row(
            raw_id="1001",
            full_name="Doe John M",
            login="jdoe",
            email_or_phone="john.doe@example.com",
            contacts="+123456",
            flags="disabled=false",
            role="Engineer",
            org_id="10",
            tab="5001",
        )
    ]
    write_csv(csv_path, rows)
    _seed_org(tmp_path, org_ouid=10)

    result, report_path = run_validate(tmp_path, csv_path, run_id="ok")

    assert result.exit_code == 0
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["rows_blocked"] == 0
    assert report["summary"]["rows_total"] == 1


def test_validate_missing_required_returns_1(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        make_row(
            raw_id="1001",
            full_name="Doe John M",
            login="jdoe",
            email_or_phone="",
            contacts="+123456",
            flags="disabled=false",
            role="Engineer",
            org_id="10",
            tab="5001",
        )
    ]
    write_csv(csv_path, rows)
    _seed_org(tmp_path, org_ouid=10)

    result, report_path = run_validate(tmp_path, csv_path, run_id="missing")

    assert result.exit_code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["rows_blocked"] == 1


def test_validate_invalid_boolean_returns_1(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        make_row(
            raw_id="1001",
            full_name="Doe John M",
            login="jdoe",
            email_or_phone="john.doe@example.com",
            contacts="+123456",
            flags="disabled=maybe",
            role="Engineer",
            org_id="10",
            tab="5001",
        )
    ]
    write_csv(csv_path, rows)
    _seed_org(tmp_path, org_ouid=10)

    result, _ = run_validate(tmp_path, csv_path, run_id="bad-bool")
    assert result.exit_code == 1


def test_validate_invalid_email_returns_1(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        make_row(
            raw_id="1001",
            full_name="Doe John M",
            login="jdoe",
            email_or_phone="john.doe@example",
            contacts="+123456",
            flags="disabled=false",
            role="Engineer",
            org_id="10",
            tab="5001",
        )
    ]
    write_csv(csv_path, rows)
    _seed_org(tmp_path, org_ouid=10)

    result, _ = run_validate(tmp_path, csv_path, run_id="bad-email")
    assert result.exit_code == 1


def test_validate_duplicate_matchkey_returns_0(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        make_row(
            raw_id="1001",
            full_name="Doe John M",
            login="jdoe",
            email_or_phone="john.doe@example.com",
            contacts="+123456",
            flags="disabled=false",
            role="Engineer",
            org_id="10",
            tab="5001",
        ),
        make_row(
            raw_id="1001",
            full_name="Doe John M",
            login="jdoe2",
            email_or_phone="john.doe2@example.com",
            contacts="+123456",
            flags="disabled=false",
            role="Engineer",
            org_id="10",
            tab="5002",
            password="SECRET2",
        ),
    ]
    write_csv(csv_path, rows)
    _seed_org(tmp_path, org_ouid=10)

    result, report_path = run_validate(tmp_path, csv_path, run_id="dup-mk")
    assert result.exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["rows_blocked"] == 0


def test_validate_duplicate_usr_org_tab_num_returns_0(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        make_row(
            raw_id="1001",
            full_name="Doe John M",
            login="jdoe",
            email_or_phone="john.doe@example.com",
            contacts="+123456",
            flags="disabled=false",
            role="Engineer",
            org_id="10",
            tab="5001",
        ),
        make_row(
            raw_id="1002",
            full_name="Doe John M",
            login="jdoe2",
            email_or_phone="john.doe2@example.com",
            contacts="+123456",
            flags="disabled=false",
            role="Engineer",
            org_id="10",
            tab="5001",
            password="SECRET2",
        ),
    ]
    write_csv(csv_path, rows)
    _seed_org(tmp_path, org_ouid=10)

    result, report_path = run_validate(tmp_path, csv_path, run_id="dup-tab")
    assert result.exit_code == 0
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["rows_blocked"] == 0


def test_validate_masks_secrets_in_report(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        make_row(
            raw_id="1001",
            full_name="Doe John M",
            login="jdoe",
            email_or_phone="",
            contacts="+123456",
            flags="disabled=false",
            role="Engineer",
            org_id="10",
            tab="5001",
            password="SECRET1",
        )
    ]
    write_csv(csv_path, rows)
    _seed_org(tmp_path, org_ouid=10)

    result, report_path = run_validate(tmp_path, csv_path, run_id="mask")
    assert result.exit_code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["items"][0]["payload"]["password"] == "***"


def test_validate_respects_report_items_limit(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        make_row(
            raw_id="1001",
            full_name="Doe John M",
            login="jdoe",
            email_or_phone="",
            contacts="+123456",
            flags="disabled=false",
            role="Engineer",
            org_id="10",
            tab="5001",
        )
        ,
        make_row(
            raw_id="1002",
            full_name="Doe John M",
            login="jdoe2",
            email_or_phone="",
            contacts="+123456",
            flags="disabled=false",
            role="Engineer",
            org_id="10",
            tab="5002",
            password="SECRET2",
        ),
    ]
    write_csv(csv_path, rows)
    _seed_org(tmp_path, org_ouid=10)

    env = {"ANKEY_REPORT_ITEMS_LIMIT": "1"}
    result, report_path = run_validate(tmp_path, csv_path, run_id="limit", env=env)
    assert result.exit_code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["meta"]["items_truncated"] is True
