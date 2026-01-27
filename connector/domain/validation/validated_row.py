from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from connector.domain.models import ValidationRowResult

T = TypeVar("T")


@dataclass
class ValidationRow(Generic[T]):
    """
    Назначение:
        Контейнер валидированной строки для передачи в этап планирования.
    """

    row: T | None
    validation: ValidationRowResult
