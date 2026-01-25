from __future__ import annotations

from dataclasses import dataclass

from connector.domain.models import ValidationErrorItem
from connector.domain.transform.source_record import SourceRecord


@dataclass(frozen=True)
class CollectResult:
    """
    Назначение:
        Результат преобразования исходной строки в SourceRecord с диагностикой.
    """

    record: SourceRecord
    errors: list[ValidationErrorItem]
    warnings: list[ValidationErrorItem]
