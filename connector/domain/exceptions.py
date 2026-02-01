from __future__ import annotations

from dataclasses import dataclass



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


__all__ = ["MissingRequiredSecretError"]
