"""
Назначение:
    Transform DSL: спецификации sink-модели.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from connector.domain.dsl.specs._base import DslBaseModel


class SinkFieldSpec(DslBaseModel):
    """
    Назначение:
        Декларативное описание поля sink-модели.
    """

    name: str
    type: Literal["string", "int", "float", "bool", "object", "list"]
    required: bool = False
    nullable: bool = False
    target: str | None = None
    generated: bool = False


class SinkBlock(DslBaseModel):
    """
    Назначение:
        Корневая секция sink-модели.
    """

    fields: list[SinkFieldSpec] = Field(default_factory=list)
    system_fields: list[SinkFieldSpec] = Field(default_factory=list)
    allow_extra: bool = True


class SinkSpec(DslBaseModel):
    """
    Назначение:
        Декларативная sink-модель для датасета.
    """

    dataset: str
    sink: SinkBlock
