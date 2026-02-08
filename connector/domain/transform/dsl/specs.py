"""
Назначение:
    Pydantic-модели DSL: правила, операции и спецификации для стадий.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class OperationCall(BaseModel):
    """
    Назначение:
        Описание вызова операции DSL.
    """

    op: str
    args: dict[str, Any] = Field(default_factory=dict)


class MappingRule(BaseModel):
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


class MetaRule(BaseModel):
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


class MappingSchema(BaseModel):
    """
    Назначение:
        Проверка результата mapping против ожидаемой структуры.
    """

    required: list[str] = Field(default_factory=list)
    allow_extra: bool = True


class MappingBlock(BaseModel):
    """
    Назначение:
        Корневая секция mapping-правил.
    """

    rules: list[MappingRule]
    schema_: MappingSchema | None = Field(default=None, alias="schema")
    meta: list[MetaRule] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
    }


class MappingSpec(BaseModel):
    """
    Назначение:
        Спецификация DSL для mapping-стадии.
    """

    dataset: str
    source_columns: list[str] = Field(default_factory=list)
    mapping: MappingBlock


class SourceFieldSpec(BaseModel):
    """
    Назначение:
        Декларативное описание поля входного источника.
    """

    name: str
    type: Literal["string", "int", "float", "bool", "object", "list"] | None = None
    required: bool = False
    nullable: bool = True
    aliases: list[str] = Field(default_factory=list)


class SourceConfig(BaseModel):
    """
    Назначение:
        Декларативная конфигурация источника датасета.
    """

    type: Literal["file", "db", "api"]
    format: str | None = None
    location: str | None = None
    location_ref: str | None = None
    options: dict[str, Any] = Field(default_factory=dict)
    fields: list[SourceFieldSpec] = Field(default_factory=list)


class SourceSpec(BaseModel):
    """
    Назначение:
        Декларативная спецификация extract-источника датасета.
    """

    dataset: str
    source: SourceConfig


class SinkFieldSpec(BaseModel):
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


class SinkBlock(BaseModel):
    """
    Назначение:
        Корневая секция sink-модели.
    """

    fields: list[SinkFieldSpec] = Field(default_factory=list)
    system_fields: list[SinkFieldSpec] = Field(default_factory=list)
    allow_extra: bool = True


class SinkSpec(BaseModel):
    """
    Назначение:
        Декларативная sink-модель для датасета.
    """

    dataset: str
    sink: SinkBlock


class NormalizeRule(BaseModel):
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


class NormalizeBlock(BaseModel):
    rules: list[NormalizeRule] = Field(default_factory=list)


class NormalizeSpec(BaseModel):
    dataset: str
    normalize: NormalizeBlock


class MatchKeySpec(BaseModel):
    fields: list[str]
    strict: bool = True


class SecretsSpec(BaseModel):
    fields: list[str] = Field(default_factory=list)


class ProviderRef(BaseModel):
    """
    Назначение:
        Ссылка на runtime provider в registry.
    """

    name: str
    args: dict[str, Any] = Field(default_factory=dict)


class ExistsRef(BaseModel):
    """
    Назначение:
        Описание exists-проверки через provider.
    """

    provider: ProviderRef


class EnrichRule(BaseModel):
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


class EnrichBlock(BaseModel):
    match_key: MatchKeySpec | None = None
    secrets: SecretsSpec | None = None
    generate: list[EnrichRule] = Field(default_factory=list)
    lookup: list[EnrichRule] = Field(default_factory=list)


class EnrichSpec(BaseModel):
    dataset: str
    enrich: EnrichBlock


class FieldCheck(BaseModel):
    field: str
    ops: list[OperationCall] = Field(default_factory=list)
    on_error: Literal["error", "warn"] = "error"


class ConditionalCheck(BaseModel):
    when: dict[str, Any]
    ops: list[OperationCall] = Field(default_factory=list)
    on_error: Literal["error", "warn"] = "error"


class ValidationBlock(BaseModel):
    field_checks: list[FieldCheck] = Field(default_factory=list)
    conditional_checks: list[ConditionalCheck] = Field(default_factory=list)


class ValidationSpec(BaseModel):
    dataset: str
    validate_: ValidationBlock = Field(alias="validate")

    model_config = {
        "populate_by_name": True,
    }


class MatchRule(BaseModel):
    """
    Назначение:
        Декларативное правило построения identity для matcher.
    """

    name: str
    fields: list[str]
    primary: str | None = None

    @model_validator(mode="after")
    def _validate_fields(self) -> "MatchRule":
        if not self.fields:
            raise ValueError("match.identity_rules[].fields must not be empty")
        if self.primary and self.primary not in self.fields:
            raise ValueError("match.identity_rules[].primary must belong to fields")
        return self


class SourceDedupSpec(BaseModel):
    """
    Назначение:
        DSL-конфигурация source-dedup политики matcher.
    """

    enabled: bool = True
    on_duplicate: Literal["warn", "error"] = "warn"
    on_conflict: Literal["warn", "error"] = "error"


class FuzzySpec(BaseModel):
    """
    Назначение:
        DSL-конфигурация fuzzy/scoring matcher.
    """

    enabled: bool = False
    blocking_keys: list[str] = Field(default_factory=list)
    comparators: dict[str, Literal["exact", "casefold", "similarity"]] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)
    accept_threshold: float = 0.90
    review_threshold: float = 0.70
    tie_delta: float = 0.05
    max_candidates: int = 50
    top_k: int = 3
    score_round: int = 4

    @model_validator(mode="after")
    def _validate_thresholds(self) -> "FuzzySpec":
        if not 0.0 <= float(self.accept_threshold) <= 1.0:
            raise ValueError("match.fuzzy.accept_threshold must be within [0.0, 1.0]")
        if not 0.0 <= float(self.review_threshold) <= 1.0:
            raise ValueError("match.fuzzy.review_threshold must be within [0.0, 1.0]")
        if float(self.review_threshold) > float(self.accept_threshold):
            raise ValueError("match.fuzzy.review_threshold must be <= match.fuzzy.accept_threshold")
        if float(self.tie_delta) < 0.0:
            raise ValueError("match.fuzzy.tie_delta must be >= 0.0")
        if int(self.max_candidates) < 1:
            raise ValueError("match.fuzzy.max_candidates must be >= 1")
        if int(self.top_k) < 1:
            raise ValueError("match.fuzzy.top_k must be >= 1")
        if int(self.score_round) < 0:
            raise ValueError("match.fuzzy.score_round must be >= 0")
        for field_name, weight in self.weights.items():
            numeric = float(weight)
            if numeric < 0.0:
                raise ValueError(f"match.fuzzy.weights[{field_name!r}] must be >= 0.0")

        comparator_fields = set(self.comparators.keys())
        weight_fields = set(self.weights.keys())
        if comparator_fields != weight_fields:
            only_comparators = sorted(comparator_fields - weight_fields)
            only_weights = sorted(weight_fields - comparator_fields)
            raise ValueError(
                "match.fuzzy.comparators and match.fuzzy.weights must define the same fields; "
                f"comparators_only={only_comparators}, weights_only={only_weights}"
            )
        return self


class MatchBlock(BaseModel):
    identity_rules: list[MatchRule] = Field(default_factory=list)
    ignored_fields: list[str] = Field(default_factory=list)
    source_dedup: SourceDedupSpec = Field(default_factory=SourceDedupSpec)
    fuzzy: FuzzySpec = Field(default_factory=FuzzySpec)

    @model_validator(mode="after")
    def _validate_identity_rules(self) -> "MatchBlock":
        if not self.identity_rules:
            raise ValueError("match.identity_rules must not be empty")
        return self


class MatchSpec(BaseModel):
    dataset: str
    match: MatchBlock


class ResolveBlock(BaseModel):
    policies: list[dict[str, Any]] = Field(default_factory=list)


class ResolveSpec(BaseModel):
    dataset: str
    resolve: ResolveBlock
