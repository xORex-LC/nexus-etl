from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from connector.domain.diagnostics.factory import DiagnosticFactory
from connector.domain.diagnostics.exceptions import DiagnosticContextNotConfiguredError
from connector.domain.models import DiagnosticItem, DiagnosticSeverity, DiagnosticStage, RowRef

_factory_var: ContextVar[DiagnosticFactory | None] = ContextVar("diagnostic_factory", default=None)


def configure(factory: DiagnosticFactory) -> None:
    """
    Назначение:
        Зарегистрировать фабрику диагностик в текущем контексте.
    """
    _factory_var.set(factory)


def get_factory() -> DiagnosticFactory:
    """
    Назначение:
        Получить текущую фабрику диагностик.
    """
    factory = _factory_var.get()
    if factory is None:
        raise DiagnosticContextNotConfiguredError()
    return factory


def error(
    stage: DiagnosticStage,
    code: str,
    field: str | None = None,
    message: str | None = None,
    record_ref: RowRef | None = None,
    details: dict[str, Any] | None = None,
    severity: DiagnosticSeverity | None = None,
) -> DiagnosticItem:
    """
    Назначение:
        Создать DiagnosticItem (error) через текущую фабрику.
    """
    return get_factory().error(
        stage=stage,
        code=code,
        field=field,
        message=message,
        record_ref=record_ref,
        details=details,
        severity=severity,
    )


def warning(
    stage: DiagnosticStage,
    code: str,
    field: str | None = None,
    message: str | None = None,
    record_ref: RowRef | None = None,
    details: dict[str, Any] | None = None,
    severity: DiagnosticSeverity | None = None,
) -> DiagnosticItem:
    """
    Назначение:
        Создать DiagnosticItem (warning) через текущую фабрику.
    """
    return get_factory().warning(
        stage=stage,
        code=code,
        field=field,
        message=message,
        record_ref=record_ref,
        details=details,
        severity=severity,
    )
