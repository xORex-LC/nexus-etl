"""
Назначение:
    Transform DSL: спецификации mapping-стадии.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from connector.domain.dsl.specs._base import DslBaseModel, OperationCall


class MappingRule(DslBaseModel):
    """
    Назначение:
        Правило mapping (source -> target/targets).

    Контракт:
        - target/targets: одно или несколько выходных полей.
        - source/sources: входные поля из источника.
        - ops: последовательность операций.
    """

    target: str | None = None
    targets: list[str] | None = None
    source: str | None = None
    sources: list[str] | None = None
    ops: list[OperationCall] = Field(default_factory=list)
    op: str | None = None
    args: dict[str, Any] | None = None
    required: bool = False
    on_error: Literal["error", "warn"] = "error"

    @model_validator(mode="after")
    def _validate_targets_sources(self) -> "MappingRule":
        if not self.target and not self.targets:
            raise ValueError("mapping rule requires target or targets")
        if self.op and not self.ops:
            self.ops = [OperationCall(op=self.op, args=self.args or {})]
        if not self.source and not self.sources:
            has_const = any(call.op == "const" for call in self.ops)
            if not has_const:
                raise ValueError("mapping rule requires source or sources")
        return self


class MetaRule(DslBaseModel):
    """
    Назначение:
        Правило формирования meta-секции результата.
    """

    target: str
    source: str | None = None
    sources: list[str] | None = None
    ops: list[OperationCall] = Field(default_factory=list)
    op: str | None = None
    args: dict[str, Any] | None = None
    on_error: Literal["error", "warn"] = "warn"

    @model_validator(mode="after")
    def _normalize_ops(self) -> "MetaRule":
        if self.op and not self.ops:
            self.ops = [OperationCall(op=self.op, args=self.args or {})]
        return self


class MappingSchema(DslBaseModel):
    """
    Назначение:
        Проверка результата mapping против ожидаемой структуры.
    """

    required: list[str] = Field(default_factory=list)
    allow_extra: bool = True


class MappingBlock(DslBaseModel):
    """
    Назначение:
        Корневая секция mapping-правил.
    """

    rules: list[MappingRule]
    schema_: MappingSchema | None = Field(default=None, alias="schema")
    meta: list[MetaRule] = Field(default_factory=list)

    model_config = {
        "extra": "forbid",
        "populate_by_name": True,
    }


class MappingSpec(DslBaseModel):
    """
    Назначение:
        Спецификация DSL для mapping-стадии.
    """

    dataset: str
    source_columns: list[str] = Field(default_factory=list)
    mapping: MappingBlock
