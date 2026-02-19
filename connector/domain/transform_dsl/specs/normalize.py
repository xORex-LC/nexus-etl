"""
Назначение:
    Transform DSL: спецификации normalize-стадии.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from connector.domain.dsl.specs._base import DslBaseModel, OperationCall


class NormalizeRule(DslBaseModel):
    """
    Назначение:
        Правило нормализации одного поля.
    """

    field: str
    ops: list[OperationCall] = Field(default_factory=list)
    op: str | None = None
    args: dict[str, Any] | None = None
    on_error: Literal["error", "warn"] = "error"

    @model_validator(mode="after")
    def _normalize_ops(self) -> "NormalizeRule":
        if self.op and not self.ops:
            self.ops = [OperationCall(op=self.op, args=self.args or {})]
        return self


class NormalizeBlock(DslBaseModel):
    on_error: Literal["error", "warn"] = "error"
    rules: list[NormalizeRule] = Field(default_factory=list)


class NormalizeSpec(DslBaseModel):
    dataset: str
    normalize: NormalizeBlock
