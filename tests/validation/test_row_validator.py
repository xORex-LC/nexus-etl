import pytest

from connector.domain.models import CsvRow
from connector.domain.validation.pipeline import RowValidator
from connector.datasets.employees.source_mapper import EmployeesSourceMapper, to_employee_input

def test_row_validator_parses_valid_row():
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
            "",
            "20",
            "Engineer",
            "",
            "TAB-100",
        ],
    )
    validator = RowValidator(EmployeesSourceMapper(), to_employee_input)
    employee, result = validator.validate(row)

    # avatarId считается ошибкой, поэтому ожидаем невалид
    assert not result.valid
    assert employee.email == "user@example.com"
    assert employee.organization_id == 20
    assert result.match_key == "Doe|John|M|100"

def test_row_validator_reports_missing_required():
    row = CsvRow(
        file_line_no=1,
        data_line_no=1,
        values=[None for _ in range(14)],  # как после parseNull в csvReader
    )
    validator = RowValidator(EmployeesSourceMapper(), to_employee_input)
    _employee, result = validator.validate(row)

    assert not result.valid
    codes = {e.code for e in result.errors}
    assert "REQUIRED_FIELD_MISSING" in codes

def test_row_validator_invalid_email():
    row = CsvRow(
        file_line_no=1,
        data_line_no=1,
        values=[
            "invalid_mail",
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
        ],
    )
    validator = RowValidator(EmployeesSourceMapper(), to_employee_input)
    _employee, result = validator.validate(row)

    assert not result.valid
    codes = {e.code for e in result.errors}
    assert "INVALID_EMAIL" in codes


def test_row_validator_produces_row_ref_even_with_errors():
    row = CsvRow(
        file_line_no=5,
        data_line_no=5,
        values=[None for _ in range(14)],
    )
    validator = RowValidator(EmployeesSourceMapper(), to_employee_input)
    _employee, result = validator.validate(row)

    assert result.row_ref is not None
    assert result.row_ref.row_id == "line:5"
    assert result.row_ref.identity_primary == "match_key"
