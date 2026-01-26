from __future__ import annotations

from dataclasses import dataclass

from connector.domain.models import RowRef
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.datasets.employees.normalized import NormalizedEmployeesRow
from connector.datasets.employees.source_mapper import EmployeesSourceMapper


def test_employees_source_mapper_builds_secrets():
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
    normalized = NormalizedEmployeesRow(
        email="user@example.com",
        last_name="Doe",
        first_name="John",
        middle_name="M",
        is_logon_disable=False,
        user_name="jdoe",
        phone="+111",
        password="secret",
        personnel_number="100",
        manager_id=None,
        organization_id=20,
        position="Engineer",
        avatar_id=None,
        usr_org_tab_num="TAB-100",
    )
    result = EmployeesSourceMapper().map(record, normalized)

    assert result.errors == []
    assert result.match_key is None
    assert result.secret_candidates.get("password") == "secret"
    assert result.row.email == "user@example.com"
    assert result.row_ref is None


def test_employees_source_mapper_does_not_add_match_key_errors():
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
    normalized = NormalizedEmployeesRow(
        email="user@example.com",
        last_name="Doe",
        first_name="John",
        middle_name=None,
        is_logon_disable=False,
        user_name="jdoe",
        phone="+111",
        password="secret",
        personnel_number="100",
        manager_id=None,
        organization_id=20,
        position="Engineer",
        avatar_id=None,
        usr_org_tab_num="TAB-100",
    )
    result = EmployeesSourceMapper().map(record, normalized)

    codes = {issue.code for issue in result.errors}
    assert "MATCH_KEY_MISSING" not in codes
    assert result.match_key is None


def test_no_secrets_source_mapper_keeps_secret_candidates_empty():
    @dataclass
    class CarRowPublic:
        vin: str

    class CarsSourceMapper(SourceMapper[NormalizedEmployeesRow, CarRowPublic]):
        def map(self, record: SourceRecord, normalized: NormalizedEmployeesRow) -> TransformResult[CarRowPublic]:
            row_ref = RowRef(
                line_no=record.line_no,
                row_id=record.record_id,
                identity_primary=None,
                identity_value=None,
            )
            return TransformResult(
                record=record,
                row=CarRowPublic(vin="VIN-1"),
                row_ref=row_ref,
                match_key=None,
            )

    record = SourceRecord(line_no=1, record_id="line:1", values={})
    normalized = NormalizedEmployeesRow(
        email=None,
        last_name=None,
        first_name=None,
        middle_name=None,
        is_logon_disable=None,
        user_name=None,
        phone=None,
        password=None,
        personnel_number=None,
        manager_id=None,
        organization_id=None,
        position=None,
        avatar_id=None,
        usr_org_tab_num=None,
    )
    result = CarsSourceMapper().map(record, normalized)
    assert result.secret_candidates == {}
