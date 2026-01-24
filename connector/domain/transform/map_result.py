from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar

from connector.domain.models import RowRef, ValidationErrorItem
from connector.domain.transform.match_key import MatchKey

T = TypeVar("T")


@dataclass
class MapResult(Generic[T]):
    """
    Назначение:
        Результат маппинга строки источника в каноническую форму.
    """

    row_ref: RowRef
    row: T
    match_key: MatchKey | None
    secret_candidates: dict[str, str] = field(default_factory=dict)
    errors: list[ValidationErrorItem] = field(default_factory=list)
    warnings: list[ValidationErrorItem] = field(default_factory=list)

    @property
    def issues(self) -> list[ValidationErrorItem]:
        return [*self.errors, *self.warnings]
