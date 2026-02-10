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


class DslLoadError(ValueError):
    """
    Назначение:
        Ошибка загрузки/валидации DSL-конфигурации.

    Контракт:
        - code: доменный код ошибки (например, CACHE_DSL_SPEC_INVALID)
        - details: контекст для отчета/логов.
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


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
