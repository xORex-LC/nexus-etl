"""
Назначение:
    Transform DSL: спецификации enrich-стадии.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from connector.domain.dsl.specs._base import DslBaseModel, OperationCall


class MatchKeySpec(DslBaseModel):
    fields: list[str]
    strict: bool = True


class SecretsSpec(DslBaseModel):
    fields: list[str] = Field(default_factory=list)


class ProviderRef(DslBaseModel):
    """
    Назначение:
        Ссылка на runtime provider в registry.
    """

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ExistsRef(DslBaseModel):
    """
    Назначение:
        Описание exists-проверки через provider.
    """

    provider: ProviderRef


class EnrichRule(DslBaseModel):
    """
    Правило enrich (generate/lookup) для одного поля.
    """

    name: str
    target: str
    provider: ProviderRef | None = None
    value_path: str | None = None
    source: str | None = None
    sources: list[str] | None = None
    ops: list[OperationCall] = Field(default_factory=list)
    on_error: Literal["error", "warn"] = "error"
    merge: Literal[
        "recompute_always",
        "fill_only_if_empty",
        "never_override",
        "override_if_empty",
        "override_if_authoritative",
    ] | None = None
    exists: ExistsRef | None = None
    allow_if: OperationCall | str | None = None
    max_attempts: int | None = None
    run_when_errors: Literal["never", "if_any", "always"] | None = None
    missing_error_code: str | None = None
    conflict_error_code: str | None = None
    error_field: str | None = None

    @model_validator(mode="after")
    def _normalize_allow_if(self) -> "EnrichRule":
        if isinstance(self.allow_if, str):
            self.allow_if = OperationCall(op=self.allow_if, args={})
        return self


class EnrichBlock(DslBaseModel):
    match_key: MatchKeySpec | None = None
    secrets: SecretsSpec | None = None
    generate: list[EnrichRule] = Field(default_factory=list)
    lookup: list[EnrichRule] = Field(default_factory=list)


class EnrichSpec(DslBaseModel):
    dataset: str
    enrich: EnrichBlock
