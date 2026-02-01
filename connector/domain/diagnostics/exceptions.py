from __future__ import annotations

from dataclasses import dataclass

from connector.domain.models import DiagnosticStage, RowRef


class UnknownDiagnosticCodeError(ValueError):
    """
    Назначение:
        Сигнализирует о неизвестном диагностическом коде в strict режиме.
    """

    def __init__(self, diag_code: str) -> None:
        super().__init__(f"Unknown diagnostic code: {diag_code}")
        self.diag_code = diag_code


@dataclass
class OperationError(Exception):
    """
    Назначение:
        Управляемое исключение, конвертируемое в DiagnosticItem на boundary.
    """

    stage: DiagnosticStage
    code: str
    message: str
    field: str | None = None
    record_ref: RowRef | None = None
    details: dict | None = None
