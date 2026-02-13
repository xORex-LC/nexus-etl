"""
Назначение:
    Базовые модели DSL: DslBaseModel, OperationCall.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DslBaseModel(BaseModel):
    """
    Назначение:
        Базовая модель для всех DSL-спецификаций.
        Запрещает неизвестные поля (typo-safe).
    """

    model_config = {"extra": "forbid"}


class OperationCall(DslBaseModel):
    """
    Назначение:
        Описание вызова операции DSL.
    """

    op: str
    args: dict[str, Any] = Field(default_factory=dict)
