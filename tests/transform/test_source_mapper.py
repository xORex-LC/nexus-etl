from __future__ import annotations

from dataclasses import dataclass

from connector.domain.models import RowRef
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.datasets.employees.source_mapper import EmployeesSourceMapper


def test_employees_source_mapper_builds_match_key_and_secrets():
    record = SourceRecord(
        line_no=1,
        record_id="line:1",
        values={
            "email": "user@example.com",
            "last_name": "Doe",
            "first_name": "John",
            "middle_name": "M",
            "is_logon_disable": False,
            "user_name": "jdoe",
            "phone": "+111",
            "password": "secret",
            "personnel_number": "100",
            "manager_id": None,
            "organization_id": 20,
            "position": "Engineer",
            "avatar_id": None,
            "usr_org_tab_num": "TAB-100",
        },
    )
    result = EmployeesSourceMapper().map(record)

    assert result.errors == []
    assert result.match_key is not None
    assert result.match_key.value == "Doe|John|M|100"
    assert result.secret_candidates.get("password") == "secret"
    assert result.row.email == "user@example.com"
    assert result.row_ref.identity_value == result.match_key.value


def test_employees_source_mapper_reports_missing_match_key():
    record = SourceRecord(
        line_no=2,
        record_id="line:2",
        values={
            "email": "user@example.com",
            "last_name": "Doe",
            "first_name": "John",
            "middle_name": None,
            "is_logon_disable": False,
            "user_name": "jdoe",
            "phone": "+111",
            "password": "secret",
            "personnel_number": "100",
            "manager_id": None,
            "organization_id": 20,
            "position": "Engineer",
            "avatar_id": None,
            "usr_org_tab_num": "TAB-100",
        },
    )
    result = EmployeesSourceMapper().map(record)

    codes = {issue.code for issue in result.errors}
    assert "MATCH_KEY_MISSING" in codes
    assert result.match_key is None


def test_no_secrets_source_mapper_keeps_secret_candidates_empty():
    @dataclass
    class CarRowPublic:
        vin: str

    class CarsSourceMapper(SourceMapper[CarRowPublic]):
        def map(self, raw: SourceRecord) -> TransformResult[CarRowPublic]:
            row_ref = RowRef(
                line_no=raw.line_no,
                row_id=raw.record_id,
                identity_primary=None,
                identity_value=None,
            )
            return TransformResult(
                record=raw,
                row=CarRowPublic(vin="VIN-1"),
                row_ref=row_ref,
                match_key=None,
            )

    record = SourceRecord(line_no=1, record_id="line:1", values={})
    result = CarsSourceMapper().map(record)
    assert result.secret_candidates == {}
