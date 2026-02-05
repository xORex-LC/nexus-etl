"""
Назначение:
    Доменные модели верхнего уровня (диагностика, идентичность, ссылки на строки).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

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
    MATCH = "MATCH"
    RESOLVE = "RESOLVE"
    PLAN = "PLAN"
    APPLY = "APPLY"
    CACHE = "CACHE"
    SINK = "SINK"


class DiagnosticSeverity(str, Enum):
    """
    Назначение:
        Уровень критичности диагностического события.
    """

    ERROR = "error"
    WARNING = "warning"


@dataclass
class DiagnosticItem:
    """
    Назначение:
        Диагностическое сообщение пайплайна (ошибка/предупреждение).
    """
    stage: DiagnosticStage
    code: str
    field: str | None
    message: str
    record_ref: "RowRef" | None = None
    details: dict[str, Any] | None = None
    severity: DiagnosticSeverity | None = None

    @classmethod
    def from_catalog(
        cls,
        *,
        catalog: Any,
        stage: DiagnosticStage,
        code: str,
        field: str | None = None,
        message: str | None = None,
        record_ref: "RowRef" | None = None,
        details: dict[str, Any] | None = None,
        severity: DiagnosticSeverity | None = None,
        default_severity: DiagnosticSeverity = DiagnosticSeverity.ERROR,
    ) -> "DiagnosticItem":
        """
        Назначение:
            Создать DiagnosticItem, используя записи ErrorCatalog.
        """
        resolved_message = catalog.resolve_message(code, message)
        resolved_severity = catalog.resolve_severity(code, severity, default_severity)
        catalog.classify(code)
        return cls(
            stage=stage,
            code=code,
            field=field,
            message=resolved_message,
            record_ref=record_ref,
            details=details,
            severity=resolved_severity,
        )


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
    secret_fields: list[str] = field(default_factory=list)
    errors: list[DiagnosticItem] = field(default_factory=list)
    warnings: list[DiagnosticItem] = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return len(self.errors) == 0

    def add_error(
        self,
        catalog,
        stage: DiagnosticStage,
        code: str,
        message: str | None = None,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> DiagnosticItem:
        from connector.domain.diagnostics.context import error as diag_error

        item = diag_error(
            catalog=catalog,
            stage=stage,
            code=code,
            field=field,
            message=message,
            record_ref=self.row_ref,
            details=details,
        )
        self.errors.append(item)
        return item


class MatchStatus(str, Enum):
    MATCHED = "matched"
    NOT_FOUND = "not_found"
    CONFLICT_TARGET = "conflict_target"
    CONFLICT_SOURCE = "conflict_source"


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
