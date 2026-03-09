"""
Назначение:
    Transform DSL: спецификации source-стадии.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from connector.domain.dsl.specs._base import DslBaseModel


class SourceFieldSpec(DslBaseModel):
    """
    Назначение:
        Декларативное описание поля входного источника.
    """

    name: str
    type: Literal["string", "int", "float", "bool", "object", "list"] | None = None
    required: bool = False
    nullable: bool = True
    aliases: list[str] = Field(default_factory=list)


class SourceConfig(DslBaseModel):
    """
    Назначение:
        Декларативная конфигурация источника датасета.
    """

    type: Literal["file", "db", "api"]
    format: str | None = None
    location: str | None = None
    location_ref: str | None = None
    has_header: bool = False
    options: dict[str, Any] = Field(default_factory=dict)
    fields: list[SourceFieldSpec] = Field(default_factory=list)


class SourceSpec(DslBaseModel):
    """
    Назначение:
        Декларативная спецификация extract-источника датасета.
    """

    dataset: str
    source: SourceConfig
