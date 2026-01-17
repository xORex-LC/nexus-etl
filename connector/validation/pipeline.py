from __future__ import annotations

from typing import Any, Callable, Protocol

from ..models import CsvRow, EmployeeInput, ValidationErrorItem, ValidationRowResult
from .deps import DatasetValidationState, ValidationDependencies
from .row_rules import FIELD_RULES, RowRule, normalize_whitespace
from .dataset_rules import MatchKeyUniqueRule, OrgExistsRule, UsrOrgTabUniqueRule

class DatasetRule(Protocol):
    """
    Назначение:
        Контракт для глобальных правил валидации набора строк.
    """

    def apply(
        self,
        employee: EmployeeInput,
        result: ValidationRowResult,
        state: DatasetValidationState,
        deps: ValidationDependencies,
        on_missing_org: str,
    ) -> None: ...

class RowValidator:
    """
    Назначение/ответственность:
        Выполняет валидацию одной строки CSV на уровне полей (парсинг/формат).

    Взаимодействия:
        - Использует набор RowRule.
        - Не выполняет глобальные проверки (уникальности, наличие org).
    """

    def __init__(self, rules: tuple[RowRule, ...]) -> None:
        self.rules = rules

    def _collect_fields(
        self, csvRow: CsvRow
    ) -> tuple[dict[str, Any], list[ValidationErrorItem], list[ValidationErrorItem]]:
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationErrorItem] = []
        values: dict[str, Any] = {}
        for rule in self.rules:
            values[rule.name] = rule.apply(csvRow.values, errors, warnings)
        return values, errors, warnings

    def validate(self, csv_row: CsvRow) -> tuple[EmployeeInput, ValidationRowResult]:
        """
        Контракт:
            csv_row: нормализованная строка CSV.
            Возвращает EmployeeInput + ValidationRowResult с ошибками/варнингами полей.
        """
        values, errors, warnings = self._collect_fields(csv_row)

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

        match_key = build_match_key(employee)
        match_key_complete = all(
            [employee.last_name, employee.first_name, employee.middle_name, employee.personnel_number]
        )

        result = ValidationRowResult(
            line_no=csv_row.file_line_no,
            match_key=match_key,
            match_key_complete=match_key_complete,
            usr_org_tab_num=employee.usr_org_tab_num,
            errors=errors,
            warnings=warnings,
        )
        return employee, result

class DatasetValidator:
    """
    Назначение/ответственность:
        Применяет глобальные правила к результатам строковой валидации, используя
        общее состояние (уникальности, наличие связанных сущностей).
    """

    def __init__(
        self,
        rules: tuple[DatasetRule, ...],
        state: DatasetValidationState,
        deps: ValidationDependencies,
        on_missing_org: str,
    ) -> None:
        self.rules = rules
        self.state = state
        self.deps = deps
        self.on_missing_org = on_missing_org

    def validate(self, employee: EmployeeInput, result: ValidationRowResult) -> None:
        """
        Контракт:
            - Модифицирует result.errors/result.warnings, обновляет state.
        """
        for rule in self.rules:
            rule.apply(employee, result, self.state, self.deps, self.on_missing_org)

def build_match_key(employee: EmployeeInput) -> str:
    parts = [
        normalize_whitespace(employee.last_name) or "",
        normalize_whitespace(employee.first_name) or "",
        normalize_whitespace(employee.middle_name) or "",
        normalize_whitespace(employee.personnel_number) or "",
    ]
    return "|".join(parts)

class ValidatorFactory:
    """
    Назначение/ответственность:
        Собирает валидаторы и контекст валидации, подставляя зависимости.
    """

    def __init__(self, deps: ValidationDependencies, on_missing_org: str = "error") -> None:
        self.deps = deps
        self.on_missing_org = on_missing_org

    def create_validation_context(self) -> DatasetValidationState:
        """
        Возвращает:
            DatasetValidationState — состояние глобальных проверок.
        """
        return DatasetValidationState(matchkey_seen={}, usr_org_tab_seen={})

    def create_row_validator(self) -> RowValidator:
        """
        Возвращает:
            RowValidator с базовыми FIELD_RULES.
        """
        return RowValidator(FIELD_RULES)

    def create_dataset_validator(self, state: DatasetValidationState) -> DatasetValidator:
        """
        Возвращает:
            DatasetValidator с набором глобальных правил.
        """
        dataset_rules: tuple[DatasetRule, ...] = (
            MatchKeyUniqueRule(),
            UsrOrgTabUniqueRule(),
            OrgExistsRule(),
        )
        return DatasetValidator(
            rules=dataset_rules,
            state=state,
            deps=self.deps,
            on_missing_org=self.on_missing_org,
        )

# Совместимость: публичные API, которые использовал остальной код
def validateEmployeeRow(csvRow: CsvRow) -> tuple[EmployeeInput, ValidationRowResult]:
    """
    Назначение:
        Совместимость: валидация одной строки через RowValidator по умолчанию.
    """
    row_validator = RowValidator(FIELD_RULES)
    return row_validator.validate(csvRow)

def validateEmployeeRowWithContext(csvRow: CsvRow, ctx) -> tuple[EmployeeInput, ValidationRowResult]:
    """
    Назначение:
        Совместимость: валидация строки с глобальными проверками через DatasetValidator.
    """
    row_validator = RowValidator(FIELD_RULES)
    employee, result = row_validator.validate(csvRow)

    # Адаптация контекста
    class _CallableOrgLookup:
        def __init__(self, fn: Callable[[int], Any]):
            self.fn = fn

        def get_org_by_id(self, ouid: int) -> Any:
            return self.fn(ouid)

    deps = ValidationDependencies(
        org_lookup=_CallableOrgLookup(ctx.org_lookup) if getattr(ctx, "org_lookup", None) else None,
        user_lookup=None,
        matchkey_lookup=None,
    )
    state = DatasetValidationState(matchkey_seen=getattr(ctx, "matchkey_seen", {}), usr_org_tab_seen=getattr(ctx, "usr_org_tab_seen", {}))
    dataset_rules: tuple[DatasetRule, ...] = (
        MatchKeyUniqueRule(),
        UsrOrgTabUniqueRule(),
        OrgExistsRule(),
    )
    dataset_validator = DatasetValidator(
        rules=dataset_rules,
        state=state,
        deps=deps,
        on_missing_org=getattr(ctx, "on_missing_org", "error"),
    )
    dataset_validator.validate(employee, result)
    return employee, result