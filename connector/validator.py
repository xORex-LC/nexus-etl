from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from .models import CsvRow, EmployeeInput, ValidationErrorItem, ValidationRowResult
from .loggingSetup import logEvent
from .protocols_lookup import MatchKeyLookupProtocol, OrgLookupProtocol, UserLookupProtocol

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass
class ValidationDependencies:
    """
    Назначение:
        Описывает внешние зависимости валидатора (кэши/репозитории), чтобы
        отделить валидацию от конкретной реализации хранилища.

    Инварианты:
        - Все поля могут быть None, если конкретная проверка не нужна.
        - Объекты реализуют соответствующие Protocol из modules protocols_lookup.py.

    Взаимодействия:
        - Передаётся фабрике валидаторов, которая решает, какие проверки включать.
    """

    org_lookup: OrgLookupProtocol | None = None
    user_lookup: UserLookupProtocol | None = None
    matchkey_lookup: MatchKeyLookupProtocol | None = None


class ValidatorFactory:
    """
    Назначение/ответственность:
        Собирает и конфигурирует валидаторы для строк и датасета, подставляя
        внешние зависимости (кэш) через интерфейсы.

    Взаимодействия:
        - Создаёт ValidationContext с нужными lookup-ами.
        - Возвращает callable для валидации строки в текущей реализации.

    Ограничения:
        - Потокобезопасность на совести вызывающего; фабрика не хранит состояния.
    """

    def __init__(self, deps: ValidationDependencies, on_missing_org: str = "error") -> None:
        """
        Контракт:
            deps: внешние источники данных (может быть пустым).
            on_missing_org: политика отсутствующей организации (пока совместимо
            с текущей реализацией).
        """
        self.deps = deps
        self.on_missing_org = on_missing_org

    def create_validation_context(self) -> ValidationContext:
        """
        Назначение:
            Формирует ValidationContext с переданными lookup-ами.

        Выходные данные:
            ValidationContext — содержит накопители уникальностей и lookup-функции.
        """
        return ValidationContext(
            matchkey_seen={},
            usr_org_tab_seen={},
            org_lookup=(lambda ouid: self.deps.org_lookup.get_org_by_id(ouid)) if self.deps.org_lookup else None,
            on_missing_org=self.on_missing_org,
        )

    def create_row_validator(self) -> Callable[[CsvRow], tuple[EmployeeInput, ValidationRowResult]]:
        """
        Назначение:
            Возвращает функцию для валидации одной строки CSV.

        Контракт:
            Принимает CsvRow, возвращает (EmployeeInput, ValidationRowResult).
            Исключения не перехватываются — вызывающий отвечает за обработку.
        """
        return validateEmployeeRow

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


@dataclass
class FieldRule:
    name: str
    index: int
    required: bool = False
    parser: Optional[
        Callable[[Any, list[ValidationErrorItem], list[ValidationErrorItem]], Any]
    ] = None
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
    if not validateEmail(str(value)):
        errors.append(ValidationErrorItem(code="INVALID_EMAIL", field="email", message="email has invalid format"))


def _boolean_parser(
    value: Any, errors: list[ValidationErrorItem], _: list[ValidationErrorItem]
) -> bool | None:
    try:
        return parseBooleanStrict(str(value))
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
            parsed = parseIntStrict(str(value))
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


@dataclass
class ValidationContext:
    matchkey_seen: dict[str, int]
    usr_org_tab_seen: dict[str, int]
    org_lookup: Callable[[int], Any] | None = None
    on_missing_org: str = "error"


def _collect_fields(csvRow: CsvRow) -> tuple[dict[str, Any], list[ValidationErrorItem], list[ValidationErrorItem]]:
    errors: list[ValidationErrorItem] = []
    warnings: list[ValidationErrorItem] = []
    values: dict[str, Any] = {}
    for rule in FIELD_RULES:
        values[rule.name] = rule.apply(csvRow.values, errors, warnings)
    return values, errors, warnings


def validateEmployeeRow(csvRow: CsvRow) -> tuple[EmployeeInput, ValidationRowResult]:
    values, errors, warnings = _collect_fields(csvRow)

    employee = EmployeeInput(
        email=values.get("email"),
        last_name=values.get("lastName"),
        first_name=values.get("firstName"),
        middle_name=values.get("middleName"),
        is_logon_disable=values.get("isLogonDisable"),
        user_name=values.get("userName"),
        phone=values.get("phone"),
        password=values.get("password"),
        personnel_number=values.get("personnelNumber"),
        manager_id=values.get("managerId"),
        organization_id=values.get("organization_id"),
        position=values.get("position"),
        avatar_id=values.get("avatarId"),
        usr_org_tab_num=values.get("usrOrgTabNum"),
    )

    match_key = buildMatchKey(employee)
    match_key_complete = all(
        [employee.last_name, employee.first_name, employee.middle_name, employee.personnel_number]
    )

    result = ValidationRowResult(
        line_no=csvRow.file_line_no,
        match_key=match_key,
        match_key_complete=match_key_complete,
        usr_org_tab_num=employee.usr_org_tab_num,
        errors=errors,
        warnings=warnings,
    )
    return employee, result


def _apply_cross_checks(
    employee: EmployeeInput,
    result: ValidationRowResult,
    ctx: ValidationContext,
) -> None:
    # Уникальность match_key
    if result.match_key_complete:
        prev_line = ctx.matchkey_seen.get(result.match_key)
        if prev_line is not None:
            result.errors.append(
                ValidationErrorItem(code="DUPLICATE_MATCHKEY", field="matchKey", message=f"duplicate of line {prev_line}")
            )
        else:
            ctx.matchkey_seen[result.match_key] = result.line_no
    else:
        result.errors.append(
            ValidationErrorItem(code="MATCH_KEY_MISSING", field="matchKey", message="match_key cannot be built")
        )

    # Уникальность usr_org_tab_num
    if result.usr_org_tab_num:
        prev_line = ctx.usr_org_tab_seen.get(result.usr_org_tab_num)
        if prev_line is not None:
            result.errors.append(
                ValidationErrorItem(
                    code="DUPLICATE_USR_ORG_TAB_NUM", field="usrOrgTabNum", message=f"duplicate of line {prev_line}"
                )
            )
        else:
            ctx.usr_org_tab_seen[result.usr_org_tab_num] = result.line_no

    # Проверка наличия организации (если есть lookup)
    if ctx.org_lookup and employee.organization_id is not None:
        org_exists = ctx.org_lookup(employee.organization_id)
        if org_exists is None:
            if ctx.on_missing_org == "error":
                result.errors.append(
                    ValidationErrorItem(
                        code="ORG_NOT_FOUND", field="organization_id", message="organization_id not found in cache"
                    )
                )
            elif ctx.on_missing_org == "warn-and-skip":
                result.warnings.append(
                    ValidationErrorItem(
                        code="ORG_NOT_FOUND", field="organization_id", message="organization_id not found in cache"
                    )
                )


def validateEmployeeRowWithContext(
    csvRow: CsvRow,
    ctx: ValidationContext,
) -> tuple[EmployeeInput, ValidationRowResult]:
    employee, result = validateEmployeeRow(csvRow)
    _apply_cross_checks(employee, result, ctx)
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
    index_str = (
        str(report_item_index)
        if report_item_index is not None
        else f"line:{result.line_no} (not stored: limit reached)"
    )
    logEvent(
        logger,
        logging.WARNING,
        run_id,
        context,
        f"invalid row line={result.line_no} report_item_index={index_str} errors={code_str}",
    )
