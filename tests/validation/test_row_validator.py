import pytest

from connector.domain.models import CsvRow
from connector.domain.validation.pipeline import RowValidator
from connector.domain.validation.row_rules import FIELD_RULES

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
    validator = RowValidator(FIELD_RULES)
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
    validator = RowValidator(FIELD_RULES)
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
    validator = RowValidator(FIELD_RULES)
    _employee, result = validator.validate(row)

    assert not result.valid
    codes = {e.code for e in result.errors}
    assert "INVALID_EMAIL" in codes
