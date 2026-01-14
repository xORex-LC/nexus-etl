from __future__ import annotations

import logging
import re

from .models import CsvRow, EmployeeInput, ValidationErrorItem, ValidationRowResult
from .loggingSetup import logEvent

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

def normalizeWhitespace(value: str | None) -> str | None:
    if value is None:
        return None
    return " ".join(value.split())

def buildMatchKey(employee: EmployeeInput) -> str:
    parts = [
        normalizeWhitespace(employee.last_name) or "",
        normalizeWhitespace(employee.first_name) or "",
        normalizeWhitespace(employee.middle_name) or "",
        normalizeWhitespace(employee.personnel_number) or "",
    ]
    return "|".join(parts)

def parseBooleanStrict(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("Invalid boolean value")

def parseIntStrict(value: str) -> int:
    if value.strip() == "":
        raise ValueError("Empty int value")
    return int(value)

def validateEmail(value: str) -> bool:
    return EMAIL_RE.match(value) is not None

def _required(value: str | None, field: str, errors: list[ValidationErrorItem]) -> None:
    if value is None:
        errors.append(ValidationErrorItem(code="REQUIRED_FIELD_MISSING", field=field, message=f"{field} is required"))

def validateEmployeeRow(csvRow: CsvRow) -> tuple[EmployeeInput, ValidationRowResult]:
    values = csvRow.values
    email = values[0]
    last_name = values[1]
    first_name = values[2]
    middle_name = values[3]
    is_logon_disable_raw = values[4]
    user_name = values[5]
    phone = values[6]
    password = values[7]
    personnel_number = values[8]
    manager_id_raw = values[9]
    organization_id_raw = values[10]
    position = values[11]
    avatar_id_raw = values[12]
    usr_org_tab_num = values[13]

    errors: list[ValidationErrorItem] = []
    warnings: list[ValidationErrorItem] = []

    _required(email, "email", errors)
    _required(last_name, "lastName", errors)
    _required(first_name, "firstName", errors)
    _required(middle_name, "middleName", errors)
    _required(is_logon_disable_raw, "isLogonDisable", errors)
    _required(user_name, "userName", errors)
    _required(phone, "phone", errors)
    _required(password, "password", errors)
    _required(personnel_number, "personnelNumber", errors)
    _required(organization_id_raw, "organization_id", errors)
    _required(position, "position", errors)
    _required(usr_org_tab_num, "usrOrgTabNum", errors)

    is_logon_disable: bool | None = None
    if is_logon_disable_raw is not None:
        try:
            is_logon_disable = parseBooleanStrict(is_logon_disable_raw)
        except ValueError:
            errors.append(
                ValidationErrorItem(
                    code="INVALID_BOOLEAN",
                    field="isLogonDisable",
                    message="isLogonDisable must be 'true' or 'false'",
                )
            )

    if email is not None and not validateEmail(email):
        errors.append(ValidationErrorItem(code="INVALID_EMAIL", field="email", message="email has invalid format"))

    organization_id: int | None = None
    if organization_id_raw is not None:
        try:
            organization_id = parseIntStrict(organization_id_raw)
            if organization_id <= 0:
                raise ValueError("organization_id must be > 0")
        except ValueError:
            errors.append(
                ValidationErrorItem(
                    code="INVALID_INT",
                    field="organization_id",
                    message="organization_id must be an integer > 0",
                )
            )

    manager_id: int | None = None
    if manager_id_raw is not None:
        try:
            manager_id = parseIntStrict(manager_id_raw)
            if manager_id <= 0:
                raise ValueError("managerId must be > 0")
        except ValueError:
            errors.append(
                ValidationErrorItem(
                    code="INVALID_INT",
                    field="managerId",
                    message="managerId must be an integer > 0",
                )
            )

    if avatar_id_raw is not None:
        errors.append(
            ValidationErrorItem(
                code="INVALID_AVATAR_ID",
                field="avatarId",
                message="avatarId must be empty or null",
            )
        )

    employee = EmployeeInput(
        email=email,
        last_name=last_name,
        first_name=first_name,
        middle_name=middle_name,
        is_logon_disable=is_logon_disable,
        user_name=user_name,
        phone=phone,
        password=password,
        personnel_number=personnel_number,
        manager_id=manager_id,
        organization_id=organization_id,
        position=position,
        avatar_id=avatar_id_raw,
        usr_org_tab_num=usr_org_tab_num,
    )

    match_key = buildMatchKey(employee)
    match_key_complete = all([last_name, first_name, middle_name, personnel_number])

    result = ValidationRowResult(
        line_no=csvRow.file_line_no,
        match_key=match_key,
        match_key_complete=match_key_complete,
        usr_org_tab_num=usr_org_tab_num,
        errors=errors,
        warnings=warnings,
    )
    return employee, result


def logValidationFailure(
    logger,
    run_id: str,
    context: str,
    result: ValidationRowResult,
    report_item_index: int | None,
    errors: list[ValidationErrorItem] | None = None,
    warnings: list[ValidationErrorItem] | None = None,
) -> None:
    """
    Логирует информацию о невалидной строке CSV.
    """
    eff_errors = errors if errors is not None else result.errors
    eff_warnings = warnings if warnings is not None else result.warnings

    codes: list[str] = []
    codes.extend(e.code for e in eff_errors)
    codes.extend(w.code for w in eff_warnings)
    code_str = ",".join(sorted(set(codes))) if codes else "none"
    logEvent(
        logger,
        logging.WARNING,
        run_id,
        context,
        f"invalid row line={result.line_no} report_item_index={report_item_index if report_item_index is not None else 'n/a'} errors={code_str}",
    )
