"""
Назначение:
    Transform DSL: спецификации source-стадии.
"""

from __future__ import annotations

import codecs
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from connector.domain.dsl.specs._base import DslBaseModel


class CsvSourceOptions(DslBaseModel):
    """
    Назначение:
        Декларативные параметры физического CSV-формата источника.
    """

    delimiter: str = ","
    encoding: str = "utf-8-sig"

    @field_validator("delimiter", mode="after")
    @classmethod
    def _validate_delimiter(cls, value: str) -> str:
        if value == "":
            raise ValueError("CSV delimiter must be non-empty")
        if len(value) != 1:
            raise ValueError("CSV delimiter must be exactly one character")
        return value

    @field_validator("encoding", mode="after")
    @classmethod
    def _validate_encoding(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("CSV encoding must be non-empty")
        try:
            codecs.lookup(normalized)
        except LookupError as exc:
            raise ValueError(f"CSV encoding is unknown: {normalized}") from exc
        return normalized


class SourceFieldSpec(DslBaseModel):
    """
    Назначение:
        Декларативное описание поля входного источника.

    Примечание:
        `name` сейчас используется как документированное имя поля источника.
        Сопоставление source -> sink выполняется mapping DSL, а `aliases` пока
        не применяются в runtime. Поле `aliases` оставлено как точка расширения
        для будущей нормализации физических имён колонок к каноническим source
        names на source boundary.
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

    @model_validator(mode="after")
    def _validate_format_options(self) -> "SourceConfig":
        if self.format == "csv":
            self.csv_options()
        return self

    def csv_options(self) -> CsvSourceOptions:
        """
        Назначение:
            Вернуть типизированные CSV options с текущими default-значениями.
        """
        return CsvSourceOptions.model_validate(self.options or {})


class SourceSpec(DslBaseModel):
    """
    Назначение:
        Декларативная спецификация extract-источника датасета.
    """

    dataset: str
    source: SourceConfig
