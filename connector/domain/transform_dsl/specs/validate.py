"""
Назначение:
    Transform DSL: спецификации validate-стадии.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from connector.domain.dsl.specs._base import DslBaseModel, OperationCall


class FieldCheck(DslBaseModel):
    field: str
    ops: list[OperationCall] = Field(default_factory=list)
    on_error: Literal["error", "warn"] = "error"


class ConditionalCheck(DslBaseModel):
    when: dict[str, Any]
    ops: list[OperationCall] = Field(default_factory=list)
    on_error: Literal["error", "warn"] = "error"


class ValidationBlock(DslBaseModel):
    field_checks: list[FieldCheck] = Field(default_factory=list)
    conditional_checks: list[ConditionalCheck] = Field(default_factory=list)


class ValidationSpec(DslBaseModel):
    dataset: str
    validate_: ValidationBlock = Field(alias="validate")

    model_config = {
        "extra": "forbid",
        "populate_by_name": True,
    }
