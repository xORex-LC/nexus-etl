from __future__ import annotations

from dataclasses import dataclass, field

@dataclass
class CsvRow:
    """
    Назначение:
        Нормализованная строка CSV.
    """
    file_line_no: int
    data_line_no: int
    values: list[str | None]

@dataclass
class EmployeeInput:
    """
    Назначение:
        Внутренняя модель данных сотрудника (нормализованная).
    """
    email: str | None
    last_name: str | None
    first_name: str | None
    middle_name: str | None
    is_logon_disable: bool | None
    user_name: str | None
    phone: str | None
    password: str | None
    personnel_number: str | None
    manager_id: int | None
    organization_id: int | None
    position: str | None
    avatar_id: str | None
    usr_org_tab_num: str | None

@dataclass
class ValidationErrorItem:
    """
    Назначение:
        Описание ошибки/предупреждения валидации.
    """
    code: str
    field: str | None
    message: str

@dataclass
class ValidationRowResult:
    """
    Назначение:
        Результат валидации одной строки CSV.
    """
    line_no: int
    match_key: str
    match_key_complete: bool
    usr_org_tab_num: str | None
    errors: list[ValidationErrorItem] = field(default_factory=list)
    warnings: list[ValidationErrorItem] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0
