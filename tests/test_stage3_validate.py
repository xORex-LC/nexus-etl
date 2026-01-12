import json
from pathlib import Path

from typer.testing import CliRunner

from connector.cli import app

runner = CliRunner()

HEADER = (
    "email;lastName;firstName;middleName;isLogonDisable;userName;phone;password;"
    "personnelNumber;managerId;organization_id;position;avatarId;usrOrgTabNum"
)

def write_csv(path: Path, rows: list[list[str]], include_header: bool = True) -> None:
    lines = []
    if include_header:
        lines.append(HEADER)
    for row in rows:
        lines.append(";".join(row))
    path.write_text("\n".join(lines), encoding="utf-8")

def run_validate(tmp_path: Path, csv_path: Path, run_id: str = "run-1"):
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
    )
    report_path = report_dir / f"report_validate_{run_id}.json"
    return result, report_path

def test_validate_ok_returns_0(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        [
            "john.doe@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe",
            "+123456",
            "SECRET1",
            "1001",
            "",
            "10",
            "Engineer",
            "",
            "5001",
        ]
    ]
    write_csv(csv_path, rows)

    result, report_path = run_validate(tmp_path, csv_path, run_id="ok")

    assert result.exit_code == 0
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["failed"] == 0
    assert report["meta"]["csv_rows_total"] == 1
    assert report["meta"]["csv_rows_processed"] == 1

def test_validate_missing_required_returns_1(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        [
            "",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe",
            "+123456",
            "SECRET1",
            "1001",
            "",
            "10",
            "Engineer",
            "",
            "5001",
        ]
    ]
    write_csv(csv_path, rows)

    result, report_path = run_validate(tmp_path, csv_path, run_id="missing")

    assert result.exit_code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["failed"] == 1

def test_validate_invalid_boolean_returns_1(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        [
            "john.doe@example.com",
            "Doe",
            "John",
            "M",
            "yes",
            "jdoe",
            "+123456",
            "SECRET1",
            "1001",
            "",
            "10",
            "Engineer",
            "",
            "5001",
        ]
    ]
    write_csv(csv_path, rows)

    result, _ = run_validate(tmp_path, csv_path, run_id="bad-bool")
    assert result.exit_code == 1

def test_validate_invalid_email_returns_1(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        [
            "john.doe@example",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe",
            "+123456",
            "SECRET1",
            "1001",
            "",
            "10",
            "Engineer",
            "",
            "5001",
        ]
    ]
    write_csv(csv_path, rows)

    result, _ = run_validate(tmp_path, csv_path, run_id="bad-email")
    assert result.exit_code == 1

def test_validate_duplicate_matchkey_returns_1(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        [
            "john.doe@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe",
            "+123456",
            "SECRET1",
            "1001",
            "",
            "10",
            "Engineer",
            "",
            "5001",
        ],
        [
            "john.doe2@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe2",
            "+123456",
            "SECRET2",
            "1001",
            "",
            "10",
            "Engineer",
            "",
            "5002",
        ],
    ]
    write_csv(csv_path, rows)

    result, report_path = run_validate(tmp_path, csv_path, run_id="dup-mk")
    assert result.exit_code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["summary"]["failed"] == 1
    assert any(
        err["code"] == "DUPLICATE_MATCHKEY"
        for err in report["items"][1]["errors"]
    )

def test_validate_duplicate_usr_org_tab_num_returns_1(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    rows = [
        [
            "john.doe@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe",
            "+123456",
            "SECRET1",
            "1001",
            "",
            "10",
            "Engineer",
            "",
            "5001",
        ],
        [
            "jane.doe@example.com",
            "Doe",
            "Jane",
            "K",
            "false",
            "jdoe2",
            "+123456",
            "SECRET2",
            "1002",
            "",
            "10",
            "Engineer",
            "",
            "5001",
        ],
    ]
    write_csv(csv_path, rows)

    result, report_path = run_validate(tmp_path, csv_path, run_id="dup-tab")
    assert result.exit_code == 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert any(
        err["code"] == "DUPLICATE_USR_ORG_TAB_NUM"
        for err in report["items"][1]["errors"]
    )

def test_validate_masks_password_in_report(tmp_path: Path):
    csv_path = tmp_path / "employees.csv"
    password = "SUPER_SECRET_PASSWORD"
    rows = [
        [
            "john.doe@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe",
            "+123456",
            password,
            "1001",
            "",
            "10",
            "Engineer",
            "",
            "5001",
        ]
    ]
    write_csv(csv_path, rows)

    result, report_path = run_validate(tmp_path, csv_path, run_id="mask")
    assert result.exit_code == 0
    report_text = report_path.read_text(encoding="utf-8")
    assert password not in report_text