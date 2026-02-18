"""
Назначение:
    Transform DSL спецификации: mapping, source, sink, normalize, enrich, validate, match, resolve.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from connector.domain.dsl.specs._base import DslBaseModel, OperationCall


# ========== MAPPING ==========


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


# ========== SOURCE ==========


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
    options: dict[str, Any] = Field(default_factory=dict)
    fields: list[SourceFieldSpec] = Field(default_factory=list)


class SourceSpec(DslBaseModel):
    """
    Назначение:
        Декларативная спецификация extract-источника датасета.
    """

    dataset: str
    source: SourceConfig


# ========== SINK ==========


class SinkFieldSpec(DslBaseModel):
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


class SinkBlock(DslBaseModel):
    """
    Назначение:
        Корневая секция sink-модели.
    """

    fields: list[SinkFieldSpec] = Field(default_factory=list)
    system_fields: list[SinkFieldSpec] = Field(default_factory=list)
    allow_extra: bool = True


class SinkSpec(DslBaseModel):
    """
    Назначение:
        Декларативная sink-модель для датасета.
    """

    dataset: str
    sink: SinkBlock


# ========== NORMALIZE ==========


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


# ========== ENRICH ==========


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


# ========== VALIDATE ==========


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


# ========== MATCH ==========


class MatchRule(DslBaseModel):
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


class SourceDedupSpec(DslBaseModel):
    """
    Назначение:
        DSL-конфигурация source-dedup политики matcher.
    """

    enabled: bool = True
    on_duplicate: Literal["warn", "error"] = "warn"
    on_conflict: Literal["warn", "error"] = "error"


class FuzzySpec(DslBaseModel):
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


class MatchBlock(DslBaseModel):
    identity_rules: list[MatchRule] = Field(default_factory=list)
    ignored_fields: list[str] = Field(default_factory=list)
    source_dedup: SourceDedupSpec = Field(default_factory=SourceDedupSpec)
    fuzzy: FuzzySpec = Field(default_factory=FuzzySpec)

    @model_validator(mode="after")
    def _validate_identity_rules(self) -> "MatchBlock":
        if not self.identity_rules:
            raise ValueError("match.identity_rules must not be empty")
        return self


class MatchSpec(DslBaseModel):
    dataset: str
    match: MatchBlock


# ========== RESOLVE ==========


class ResolveDesiredStateSpec(DslBaseModel):
    """
    Назначение:
        Декларативная сборка desired_state из входной строки.
    """

    mode: Literal["project_fields"] = "project_fields"
    fields: list[str] = Field(default_factory=list)
    drop_fields: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_fields(self) -> "ResolveDesiredStateSpec":
        if not self.fields:
            raise ValueError("resolve.desired_state.fields must not be empty")
        return self


class ResolveSourceRefSpec(DslBaseModel):
    """
    Назначение:
        Декларативная сборка source_ref из identity.
    """

    mode: Literal["from_identity"] = "from_identity"
    fields: list[str] = Field(default_factory=list)
    include_primary: bool = True


class ResolveDiffFieldSpec(DslBaseModel):
    """
    Назначение:
        Декларативное сравнение одного поля в diff-policy.
    """

    field: str
    existing: str | None = None
    output: str | None = None
    normalize: Literal["none", "text", "bool"] = "none"


class ResolveDiffSpec(DslBaseModel):
    """
    Назначение:
        Декларативный diff-policy resolver.
    """

    class FromSinkSpec(DslBaseModel):
        """
        Назначение:
            Конфигурация генерации базовых diff-полей из sink-спеки.
        """

        enabled: bool = False
        exclude_fields: list[str] = Field(default_factory=list)
        normalize_by_type: bool = True

    mode: Literal["compare_fields"] = "compare_fields"
    fields: list[ResolveDiffFieldSpec] = Field(default_factory=list)
    ignore_fields: list[str] = Field(default_factory=list)
    from_sink: FromSinkSpec = Field(default_factory=FromSinkSpec)

    @model_validator(mode="after")
    def _validate_fields(self) -> "ResolveDiffSpec":
        if not self.fields and not self.from_sink.enabled:
            raise ValueError(
                "resolve.diff.fields must not be empty when resolve.diff.from_sink.enabled is false"
            )
        return self


class ResolveMergeFieldSpec(DslBaseModel):
    """
    Назначение:
        Правило merge для fill_empty_from_existing.
    """

    field: str
    existing: str | None = None
    normalize: Literal["none", "text", "bool"] = "none"


class ResolveMergeSpec(DslBaseModel):
    """
    Назначение:
        Декларативная merge-policy resolver.
    """

    mode: Literal["none", "fill_empty_from_existing"] = "none"
    fields: list[ResolveMergeFieldSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_fields(self) -> "ResolveMergeSpec":
        if self.mode == "fill_empty_from_existing" and not self.fields:
            raise ValueError("resolve.merge.fields must not be empty for fill_empty_from_existing")
        return self


class ResolveSecretsSpec(DslBaseModel):
    """
    Назначение:
        Декларативная политика секретов для resolver output.
    """

    class LifecycleSpec(DslBaseModel):
        """
        Назначение:
            Декларативная политика retention для секретов в apply-runtime.
        """

        mode: Literal["persistent", "ephemeral"] = "persistent"
        delete_on_success: bool | None = None
        ttl_seconds: int | None = None

        @model_validator(mode="after")
        def _validate_ttl(self) -> "ResolveSecretsSpec.LifecycleSpec":
            if self.ttl_seconds is not None and self.ttl_seconds <= 0:
                raise ValueError("resolve.secrets.lifecycle.ttl_seconds must be greater than 0")
            return self

    mode: Literal["none", "by_op"] = "none"
    create: list[str] = Field(default_factory=list)
    update: list[str] = Field(default_factory=list)
    lifecycle: LifecycleSpec | None = None


class ResolveLinkKeySpec(DslBaseModel):
    """
    Назначение:
        Декларативный ключ поиска для link-resolve.
    """

    name: str
    field: str


class ResolveLinkSpec(DslBaseModel):
    """
    Назначение:
        Декларативное resolve-правило для одного link-поля.
    """

    field: str
    target_dataset: str
    resolve_keys: list[ResolveLinkKeySpec] = Field(default_factory=list)
    dedup_rules: list[list[str]] = Field(default_factory=list)
    target_id_field: str = "_id"
    coerce: Literal["int", "str"] | None = None
    on_unresolved: Literal["pending", "hard_error"] = "pending"

    @model_validator(mode="after")
    def _validate_link(self) -> "ResolveLinkSpec":
        if not self.resolve_keys:
            raise ValueError("resolve.links[].resolve_keys must not be empty")
        for idx, rule in enumerate(self.dedup_rules):
            if not rule:
                raise ValueError(f"resolve.links[].dedup_rules[{idx}] must not be empty")
            for key_name in rule:
                if not str(key_name).strip():
                    raise ValueError(
                        f"resolve.links[].dedup_rules[{idx}] must not contain empty key names"
                    )
        return self


class ResolveBlock(DslBaseModel):
    desired_state: ResolveDesiredStateSpec | None = None
    source_ref: ResolveSourceRefSpec | None = None
    diff: ResolveDiffSpec | None = None
    merge: ResolveMergeSpec | None = None
    secrets: ResolveSecretsSpec | None = None
    links: list[ResolveLinkSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_block(self) -> "ResolveBlock":
        fields = [item.field for item in self.links]
        duplicates = sorted({name for name in fields if fields.count(name) > 1})
        if duplicates:
            raise ValueError(f"resolve.links has duplicate field entries: {duplicates}")
        if self.desired_state is None:
            raise ValueError("resolve.desired_state is required")
        if self.diff is None:
            raise ValueError("resolve.diff is required")
        return self


class ResolveSpec(DslBaseModel):
    dataset: str
    resolve: ResolveBlock
