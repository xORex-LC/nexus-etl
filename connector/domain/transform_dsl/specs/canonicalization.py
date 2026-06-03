"""Transform DSL: shared canonicalization spec для comparison/lookups.

Модуль описывает transport-neutral декларативный shape canonicalization ops,
который может переиспользоваться topology, cache lookup и другими comparison
consumer-ами без привязки к конкретной стадии.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, field_validator

from connector.domain.dsl.specs._base import DslBaseModel


class TrimOpSpec(DslBaseModel):
    """Декларативный trim-оператор shared canonicalizer-а."""

    op: Literal["trim"] = "trim"


class LowerOpSpec(DslBaseModel):
    """Декларативный lower-оператор shared canonicalizer-а."""

    op: Literal["lower"] = "lower"


class CompactOpSpec(DslBaseModel):
    """Декларативный compact-оператор shared canonicalizer-а."""

    op: Literal["compact"] = "compact"


class RegexReplaceOpSpec(DslBaseModel):
    """Декларативный regex_replace-оператор shared canonicalizer-а."""

    op: Literal["regex_replace"] = "regex_replace"
    pattern: str
    repl: str

    @field_validator("pattern", mode="after")
    @classmethod
    def _validate_pattern(cls, value: str) -> str:
        if value == "":
            raise ValueError("canonicalization.ops[].pattern must not be empty")
        return value


CanonicalizeOpSpec = Annotated[
    TrimOpSpec | LowerOpSpec | CompactOpSpec | RegexReplaceOpSpec,
    Field(discriminator="op"),
]


class CanonicalizationSpec(DslBaseModel):
    """Общий declarative contract для scalar/segment canonicalization."""

    ops: list[CanonicalizeOpSpec] = Field(default_factory=list)
