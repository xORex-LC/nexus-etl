"""
Назначение:
    Базовые диагностические сущности DSL-движка (без привязки к ErrorCatalog).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DslSeverity(str, Enum):
    """
    Назначение:
        Локальная severity для DSL-движка (ошибка/предупреждение).
    """

    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class DslIssue:
    """
    Назначение:
        Диагностическая запись DSL-движка.

    Поля:
        code: код ошибки для последующего маппинга в DiagnosticItem.
        message: текст ошибки.
        field: целевое поле (если есть).
        details: дополнительные детали.
        severity: локальная severity.
    """

    code: str
    message: str
    field: str | None = None
    details: dict[str, Any] | None = None
    severity: DslSeverity = DslSeverity.ERROR
