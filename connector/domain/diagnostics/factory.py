from __future__ import annotations

from typing import Any

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.models import DiagnosticItem, DiagnosticSeverity, DiagnosticStage, RowRef


class DiagnosticFactory:
    """
    Назначение:
        Единая фабрика для создания диагностических событий.
    """

    def __init__(self, catalog: ErrorCatalog) -> None:
        self.catalog = catalog

    def error(
        self,
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
            Создать ошибку диагностики с учётом каталога.
        """
        resolved_message = self.catalog.resolve_message(code, message)
        resolved_severity = self.catalog.resolve_severity(code, severity, DiagnosticSeverity.ERROR)
        self.catalog.classify(code)
        return DiagnosticItem(
            stage=stage,
            code=code,
            field=field,
            message=resolved_message,
            record_ref=record_ref,
            details=details,
            severity=resolved_severity,
        )

    def warning(
        self,
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
            Создать предупреждение диагностики с учётом каталога.
        """
        resolved_message = self.catalog.resolve_message(code, message)
        resolved_severity = self.catalog.resolve_severity(code, severity, DiagnosticSeverity.WARNING)
        self.catalog.classify(code)
        return DiagnosticItem(
            stage=stage,
            code=code,
            field=field,
            message=resolved_message,
            record_ref=record_ref,
            details=details,
            severity=resolved_severity,
        )
