import pytest

from connector.domain.validation.pipeline import TypedRowValidator
from connector.domain.transform.result import TransformResult
from connector.domain.transform.source_record import SourceRecord
from connector.datasets.employees.source_mapper import EmployeesSourceMapper
from connector.datasets.employees.field_rules import FIELD_RULES
from connector.datasets.employees.mapping_spec import EmployeesMappingSpec


def _to_canonical_keys(values: dict[str, object]) -> dict[str, object]:
    return {
        "email": values.get("email"),
        "last_name": values.get("lastName"),
        "first_name": values.get("firstName"),
        "middle_name": values.get("middleName"),
        "is_logon_disable": values.get("isLogonDisable"),
        "user_name": values.get("userName"),
        "phone": values.get("phone"),
        "password": values.get("password"),
        "personnel_number": values.get("personnelNumber"),
        "manager_id": values.get("managerId"),
        "organization_id": values.get("organization_id"),
        "position": values.get("position"),
        "avatar_id": values.get("avatarId"),
        "usr_org_tab_num": values.get("usrOrgTabNum"),
    }


def _collect(values: list[str | None], line_no: int = 1) -> TransformResult[None]:
    errors = []
    warnings = []
    mapped: dict[str, object] = {}
    for rule in FIELD_RULES:
        mapped[rule.name] = rule.apply(values, errors, warnings)
    record = SourceRecord(
        line_no=line_no,
        record_id=f"line:{line_no}",
        values=_to_canonical_keys(mapped),
    )
    return TransformResult(
        record=record,
        row=None,
        row_ref=None,
        match_key=None,
        errors=errors,
        warnings=warnings,
    )

def test_row_validator_parses_valid_row():
    collected = _collect(
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
        ],
        line_no=1,
    )
    mapping_spec = EmployeesMappingSpec()
    validator = TypedRowValidator(EmployeesSourceMapper(mapping_spec), mapping_spec.required_fields)
    entity, result = validator.validate(collected)

    # avatarId считается ошибкой, поэтому ожидаем невалид
    assert not result.valid
    assert entity.email == "user@example.com"
    assert entity.organization_id == 20
    assert result.match_key == "Doe|John|M|100"

def test_row_validator_reports_missing_required():
    collected = _collect([None for _ in range(14)], line_no=1)
    mapping_spec = EmployeesMappingSpec()
    validator = TypedRowValidator(EmployeesSourceMapper(mapping_spec), mapping_spec.required_fields)
    _employee, result = validator.validate(collected)

    assert not result.valid
    codes = {e.code for e in result.errors}
    assert "REQUIRED_FIELD_MISSING" in codes

def test_row_validator_invalid_email():
    collected = _collect(
        [
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
        line_no=1,
    )
    mapping_spec = EmployeesMappingSpec()
    validator = TypedRowValidator(EmployeesSourceMapper(mapping_spec), mapping_spec.required_fields)
    _employee, result = validator.validate(collected)

    assert not result.valid
    codes = {e.code for e in result.errors}
    assert "INVALID_EMAIL" in codes


def test_row_validator_produces_row_ref_even_with_errors():
    collected = _collect([None for _ in range(14)], line_no=5)
    mapping_spec = EmployeesMappingSpec()
    validator = TypedRowValidator(EmployeesSourceMapper(mapping_spec), mapping_spec.required_fields)
    _employee, result = validator.validate(collected)

    assert result.row_ref is not None
    assert result.row_ref.row_id == "line:5"
    assert result.row_ref.identity_primary == "match_key"
