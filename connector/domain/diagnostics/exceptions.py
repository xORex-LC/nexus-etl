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


class DiagnosticContextNotConfiguredError(RuntimeError):
    """
    Назначение:
        Сигнализирует об использовании diagnostics без configure().
    """

    def __init__(self) -> None:
        super().__init__("DiagnosticFactory is not configured. Call diagnostics.configure(...) first.")


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


@dataclass
class MissingRequiredSecretError(Exception):
    """
    Назначение:
        Ошибка прикладного уровня, сигнализирующая об отсутствии обязательного секрета.
    Инварианты/гарантии:
        - code установлен в "SECRET_REQUIRED".
        - Содержит контекст записи (dataset, field, row_id/line_no, target_id).
    """

    dataset: str
    field: str
    row_id: str | None = None
    line_no: int | None = None
    target_id: str | None = None

    @property
    def code(self) -> str:
        return "SECRET_REQUIRED"

    def __str__(self) -> str:
        return (
            f"Missing required secret '{self.field}' "
            f"(dataset={self.dataset}, row_id={self.row_id}, line_no={self.line_no}, target_id={self.target_id})"
        )
