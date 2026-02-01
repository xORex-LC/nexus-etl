from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from typing import Generic, TypeVar

from connector.domain.models import DiagnosticStage, RowRef, DiagnosticItem
from connector.domain.diagnostics.context import error as diag_error, warning as diag_warning
from connector.domain.transform.match_key import MatchKey
from connector.domain.transform.source_record import SourceRecord

T = TypeVar("T")


@dataclass
class TransformResult(Generic[T]):
    """
    Назначение:
        Унифицированный результат transform-пайплайна для этапов collect/map/validate.
    """

    record: SourceRecord
    row: T | None
    row_ref: RowRef | None
    match_key: MatchKey | None
    meta: dict[str, Any] = field(default_factory=dict)
    secret_candidates: dict[str, str] = field(default_factory=dict)
    errors: list[DiagnosticItem] = field(default_factory=list)
    warnings: list[DiagnosticItem] = field(default_factory=list)

    @property
    def issues(self) -> list[DiagnosticItem]:
        return [*self.errors, *self.warnings]

    def add_error(
        self,
        stage: DiagnosticStage,
        code: str,
        message: str | None = None,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> DiagnosticItem:
        """
        Назначение:
            Добавить диагностическую ошибку через DiagnosticFactory.
        """
        item = diag_error(
            stage=stage,
            code=code,
            field=field,
            message=message,
            record_ref=self.row_ref,
            details=details,
        )
        self.errors.append(item)
        return item

    def add_warning(
        self,
        stage: DiagnosticStage,
        code: str,
        message: str | None = None,
        field: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> DiagnosticItem:
        """
        Назначение:
            Добавить диагностическое предупреждение через DiagnosticFactory.
        """
        item = diag_warning(
            stage=stage,
            code=code,
            field=field,
            message=message,
            record_ref=self.row_ref,
            details=details,
        )
        self.warnings.append(item)
        return item
