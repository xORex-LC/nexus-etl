from __future__ import annotations

from typing import Any

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.diagnostics.core_catalog import build_core_catalog
from connector.domain.diagnostics.factory import DiagnosticFactory
from connector.domain.models import DiagnosticItem, DiagnosticSeverity, DiagnosticStage, RowRef

_factory: DiagnosticFactory | None = None


def configure(factory: DiagnosticFactory) -> None:
    """
    Назначение:
        Зарегистрировать фабрику диагностик (composition root).
    """
    global _factory
    _factory = factory


def get_factory() -> DiagnosticFactory:
    """
    Назначение:
        Получить текущую фабрику диагностик.
    """
    global _factory
    if _factory is None:
        _factory = DiagnosticFactory(build_core_catalog(strict=False))
    return _factory


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
