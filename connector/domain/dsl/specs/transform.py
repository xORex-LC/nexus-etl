"""
Назначение:
    Переиспользуемые DSL-блоки для source/sources + ops и условных stage-контрактов.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from connector.domain.dsl.specs._base import DslBaseModel, OperationCall


class SourceOpsBlock(DslBaseModel):
    """
    Назначение:
        Универсальный декларативный блок чтения source/sources и применения ops.

    Инварианты:
        - должен быть указан ровно один источник: `source` или `sources`;
        - порядок `ops` является частью DSL-контракта.
    """

    source: str | None = None
    sources: list[str] | None = None
    ops: list[OperationCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_source_shape(self) -> "SourceOpsBlock":
        has_source = self.source is not None
        has_sources = self.sources is not None
        if has_source == has_sources:
            raise ValueError("exactly one of 'source' or 'sources' must be provided")
        return self
