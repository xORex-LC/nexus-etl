"""
Назначение:
    Исключения диагностического слоя.
"""

from __future__ import annotations

from dataclasses import dataclass


class UnknownDiagnosticCodeError(ValueError):
    """
    Назначение:
        Сигнализирует о неизвестном диагностическом коде в strict режиме.
    """

    def __init__(self, diag_code: str) -> None:
        super().__init__(f"Unknown diagnostic code: {diag_code}")
        self.diag_code = diag_code


@dataclass
class MissingRequiredSecretError(Exception):
    """
    Назначение:
        Ошибка прикладного уровня, сигнализирующая об отсутствии обязательного секрета.
    Инварианты/гарантии:
        - code содержит диагностический `SECRET_*` код для apply boundary.
        - Содержит контекст записи (dataset, field, row_id/line_no, target_id).
    """

    dataset: str
    field: str
    row_id: str | None = None
    line_no: int | None = None
    target_id: str | None = None
    diag_code: str = "SECRET_REQUIRED"

    @property
    def code(self) -> str:
        return self.diag_code

    def __str__(self) -> str:
        return (
            f"Missing required secret '{self.field}' "
            f"(dataset={self.dataset}, row_id={self.row_id}, line_no={self.line_no}, target_id={self.target_id})"
        )
