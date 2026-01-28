from __future__ import annotations

from dataclasses import dataclass

from connector.domain.models import RowRef
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.datasets.employees.extract.source_mapper import EmployeesSourceMapper


def test_employees_source_mapper_builds_secrets():
    record = SourceRecord(
        line_no=1,
        record_id="line:1",
        values={
            "raw_id": "100",
            "full_name": "Doe John M",
            "login": "jdoe",
            "email_or_phone": "user@example.com",
            "contacts": "+111",
            "org": "Org=Engineering",
            "manager": "",
            "flags": "disabled=false",
            "employment": "role=Engineer",
            "extra": "password=secret;org_id=20;tab=TAB-100",
        },
    )
    result = EmployeesSourceMapper().map(record)

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
            "raw_id": "100",
            "full_name": "Doe John",
            "login": "jdoe",
            "email_or_phone": "user@example.com",
            "contacts": "+111",
            "org": "Org=Engineering",
            "manager": "",
            "flags": "disabled=false",
            "employment": "role=Engineer",
            "extra": "password=secret;org_id=20;tab=TAB-100",
        },
    )
    result = EmployeesSourceMapper().map(record)

    codes = {issue.code for issue in result.errors}
    assert "MATCH_KEY_MISSING" not in codes
    assert result.match_key is None


def test_no_secrets_source_mapper_keeps_secret_candidates_empty():
    @dataclass
    class CarRowPublic:
        vin: str

    class CarsSourceMapper(SourceMapper[CarRowPublic]):
        def map(self, record: SourceRecord) -> TransformResult[CarRowPublic]:
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
    result = CarsSourceMapper().map(record)
    assert result.secret_candidates == {}
