from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

class DiagnosticStage(str, Enum):
    """
    Назначение:
        Источник диагностического события в пайплайне.
    """

    EXTRACT = "EXTRACT"
    MAP = "MAP"
    NORMALIZE = "NORMALIZE"
    ENRICH = "ENRICH"
    VALIDATE = "VALIDATE"
    PLAN = "PLAN"
    APPLY = "APPLY"


@dataclass
class ValidationErrorItem:
    """
    Назначение:
        Диагностическое сообщение пайплайна (ошибка/предупреждение).
    """
    stage: DiagnosticStage
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
    row_ref: "RowRef" | None = None
    secret_candidates: dict[str, str] = field(default_factory=dict)
    errors: list[ValidationErrorItem] = field(default_factory=list)
    warnings: list[ValidationErrorItem] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0


class MatchStatus(str, Enum):
    MATCHED = "matched"
    CONFLICT = "conflict"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class MatchResult:
    """
    Назначение:
        Типизированный результат поиска/сопоставления по match_key.

    Поля:
        status: MatchStatus
        candidate: выбранный пользователь (если matched, иначе None)
        candidates: список всех найденных кандидатов после фильтров
    """
    status: MatchStatus
    candidate: dict | None
    candidates: list[dict]


@dataclass(frozen=True)
class Identity:
    """
    Назначение:
        Унифицированное представление ключей сопоставления для сущностей разных датасетов.

    Поля:
        primary: имя первичного ключа (например, "match_key" или "ouid").
        values: словарь значений ключей для сопоставления/аудита.
    """
    primary: str
    values: Mapping[str, str]

    @property
    def primary_value(self) -> str:
        return self.values.get(self.primary, "")


@dataclass(frozen=True)
class RowRef:
    """
    Назначение:
        Унифицированная ссылка на строку входного набора для отчётов.
    """
    line_no: int
    row_id: str
    identity_primary: str | None
    identity_value: str | None
