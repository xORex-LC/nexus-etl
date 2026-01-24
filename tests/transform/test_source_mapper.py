from __future__ import annotations

from dataclasses import dataclass

from connector.domain.models import CsvRow, RowRef
from connector.domain.ports.sources import SourceMapper
from connector.domain.transform.map_result import MapResult
from connector.datasets.employees.source_mapper import EmployeesSourceMapper


def test_employees_source_mapper_builds_match_key_and_secrets():
    row = CsvRow(
        file_line_no=1,
        data_line_no=1,
        values=[
            "user@example.com",
            "Doe",
            "John",
            "M",
            "false",
            "jdoe",
            "+111",
            "secret",
            "100",
            None,
            "20",
            "Engineer",
            None,
            "TAB-100",
        ],
    )
    result = EmployeesSourceMapper().map(row)

    assert result.errors == []
    assert result.match_key is not None
    assert result.match_key.value == "Doe|John|M|100"
    assert result.secret_candidates.get("password") == "secret"
    assert result.row.email == "user@example.com"
    assert result.row_ref.identity_value == result.match_key.value


def test_employees_source_mapper_reports_missing_match_key():
    row = CsvRow(
        file_line_no=2,
        data_line_no=2,
        values=[
            "user@example.com",
            "Doe",
            "John",
            None,
            "false",
            "jdoe",
            "+111",
            "secret",
            "100",
            None,
            "20",
            "Engineer",
            None,
            "TAB-100",
        ],
    )
    result = EmployeesSourceMapper().map(row)

    codes = {issue.code for issue in result.errors}
    assert "MATCH_KEY_MISSING" in codes
    assert result.match_key is None


def test_no_secrets_source_mapper_keeps_secret_candidates_empty():
    @dataclass
    class CarRowPublic:
        vin: str

    class CarsSourceMapper(SourceMapper[CarRowPublic]):
        def map(self, raw: CsvRow) -> MapResult[CarRowPublic]:
            row_ref = RowRef(
                line_no=raw.file_line_no,
                row_id=f"line:{raw.file_line_no}",
                identity_primary=None,
                identity_value=None,
            )
            return MapResult(row_ref=row_ref, row=CarRowPublic(vin="VIN-1"), match_key=None)

    row = CsvRow(file_line_no=1, data_line_no=1, values=[])
    result = CarsSourceMapper().map(row)
    assert result.secret_candidates == {}
