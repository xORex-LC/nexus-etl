"""
Назначение:
    Transform DSL: спецификации enrich-стадии.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from connector.domain.dsl.specs import DslBaseModel, OperationCall, SourceOpsBlock


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


class EnrichConditionalBlock(SourceOpsBlock):
    """
    Назначение:
        Общий enrich-блок условного чтения source/sources и применения ops.

    Примечание:
        Форма блока переиспользуема и не содержит enrich runtime semantics.
    """


class EnrichConflictPolicy(DslBaseModel):
    """
    Назначение:
        Stage-specific политика обработки exists-конфликта для generate-правил enrich.
    """

    strategy: Literal["error", "retry_with_suffixes"]
    suffixes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_suffixes(self) -> "EnrichConflictPolicy":
        if self.strategy == "retry_with_suffixes" and not self.suffixes:
            raise ValueError("retry_with_suffixes requires non-empty suffixes")
        return self


class EnrichRule(DslBaseModel):
    """
    Правило enrich (generate/lookup) для одного поля.
    """

    name: str
    target: str
    build: SourceOpsBlock | None = None
    when: EnrichConditionalBlock | None = None
    then: EnrichConditionalBlock | None = None
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
    on_conflict: EnrichConflictPolicy | None = None
    max_attempts: int | None = None
    run_when_errors: Literal["never", "if_any", "always"] | None = None
    missing_error_code: str | None = None
    conflict_error_code: str | None = None
    error_field: str | None = None

    @model_validator(mode="after")
    def _normalize_allow_if(self) -> "EnrichRule":
        if isinstance(self.allow_if, str):
            self.allow_if = OperationCall(op=self.allow_if, args={})
        if self.then is not None and self.when is None:
            raise ValueError("'then' requires 'when'")
        return self


class EnrichBlock(DslBaseModel):
    match_key: MatchKeySpec | None = None
    secrets: SecretsSpec | None = None
    generate: list[EnrichRule] = Field(default_factory=list)
    lookup: list[EnrichRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_lookup_contract(self) -> "EnrichBlock":
        for rule in self.lookup:
            if any(
                value is not None
                for value in (
                    rule.build,
                    rule.when,
                    rule.then,
                    rule.on_conflict,
                )
            ):
                raise ValueError(
                    "lookup rules must not declare build/when/then/on_conflict"
                )
        return self


class EnrichSpec(DslBaseModel):
    dataset: str
    enrich: EnrichBlock
