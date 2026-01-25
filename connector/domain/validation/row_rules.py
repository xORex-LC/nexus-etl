from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional, Protocol

from ..models import ValidationErrorItem

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

class RowRule(Protocol):
    """
    Назначение:
        Контракт для строкового правила валидации/парсинга.
    """

    name: str

    def apply(self, row_values: list[Any], errors: list[ValidationErrorItem], warnings: list[ValidationErrorItem]) -> Any: ...

def normalize_whitespace(value: str | None) -> str | None:
    """
    Назначение:
        Нормализует пробелы в строке.
    """
    if value is None:
        return None
    return " ".join(value.split())

def validate_email(value: str) -> bool:
    return EMAIL_RE.match(value) is not None

def parse_boolean_strict(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized == "true":
        return True
    if normalized == "false":
        return False
    raise ValueError("Invalid boolean value")

def parse_int_strict(value: str) -> int:
    if value.strip() == "":
        raise ValueError("Empty int value")
    return int(value)

@dataclass
class FieldRule:
    """
    Назначение:
        Общее строковое правило: берёт значение по индексу, парсит, валидирует.

    Контракт:
        - apply(row_values, errors, warnings) -> parsed_value | None
    """

    name: str
    index: int
    required: bool = False
    parser: Optional[Callable[[Any, list[ValidationErrorItem], list[ValidationErrorItem]], Any]] = None
    validators: tuple[Callable[[Any, list[ValidationErrorItem], list[ValidationErrorItem]], None], ...] = ()

    def apply(self, row_values: list[Any], errors: list[ValidationErrorItem], warnings: list[ValidationErrorItem]) -> Any:
        raw = row_values[self.index] if self.index < len(row_values) else None
        if self.required and raw is None:
            errors.append(
                ValidationErrorItem(code="REQUIRED_FIELD_MISSING", field=self.name, message=f"{self.name} is required")
            )
        if raw is None:
            return None
        parsed = raw
        if self.parser:
            parsed = self.parser(raw, errors, warnings)
        for validator in self.validators:
            validator(parsed, errors, warnings)
        return parsed

def _email_validator(value: Any, errors: list[ValidationErrorItem], _: list[ValidationErrorItem]) -> None:
    if value is None:
        return
    if not validate_email(str(value)):
        errors.append(ValidationErrorItem(code="INVALID_EMAIL", field="email", message="email has invalid format"))

def _boolean_parser(value: Any, errors: list[ValidationErrorItem], _: list[ValidationErrorItem]) -> bool | None:
    try:
        return parse_boolean_strict(str(value))
    except ValueError:
        errors.append(
            ValidationErrorItem(
                code="INVALID_BOOLEAN",
                field="isLogonDisable",
                message="isLogonDisable must be 'true' or 'false'",
            )
        )
        return None

def _int_gt_zero_parser(field: str) -> Callable[[Any, list[ValidationErrorItem], list[ValidationErrorItem]], int | None]:
    def _inner(value: Any, errors: list[ValidationErrorItem], _: list[ValidationErrorItem]) -> int | None:
        try:
            parsed = parse_int_strict(str(value))
            if parsed <= 0:
                raise ValueError()
            return parsed
        except ValueError:
            errors.append(
                ValidationErrorItem(
                    code="INVALID_INT",
                    field=field,
                    message=f"{field} must be an integer > 0",
                )
            )
            return None

    return _inner

def _avatar_validator(value: Any, errors: list[ValidationErrorItem], _: list[ValidationErrorItem]) -> None:
    if value is not None:
        errors.append(
            ValidationErrorItem(
                code="INVALID_AVATAR_ID",
                field="avatarId",
                message="avatarId must be empty or null",
            )
        )

FIELD_RULES: tuple[FieldRule, ...] = (
    # TODO: TECHDEBT - move FIELD_RULES to datasets/employees/field_rules.py to keep domain dataset-agnostic.
    # TODO: TECHDEBT - make password optional at source-parse stage; enforce on sink/create after enrich.
    FieldRule("email", 0, required=True, validators=(_email_validator,)),
    FieldRule("lastName", 1, required=True),
    FieldRule("firstName", 2, required=True),
    FieldRule("middleName", 3, required=True),
    FieldRule("isLogonDisable", 4, required=True, parser=_boolean_parser),
    FieldRule("userName", 5, required=True),
    FieldRule("phone", 6, required=True),
    FieldRule("password", 7, required=True),
    FieldRule("personnelNumber", 8, required=True),
    FieldRule("managerId", 9, parser=_int_gt_zero_parser("managerId")),
    FieldRule("organization_id", 10, required=True, parser=_int_gt_zero_parser("organization_id")),
    FieldRule("position", 11, required=True),
    FieldRule("avatarId", 12, validators=(_avatar_validator,)),
    FieldRule("usrOrgTabNum", 13, required=True),
)
