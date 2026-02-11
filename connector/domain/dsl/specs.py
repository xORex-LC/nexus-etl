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
    on_error: Literal["error", "warn"] = "error"
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


class ResolveDesiredStateSpec(BaseModel):
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


class ResolveSourceRefSpec(BaseModel):
    """
    Назначение:
        Декларативная сборка source_ref из identity.
    """

    mode: Literal["from_identity"] = "from_identity"
    fields: list[str] = Field(default_factory=list)
    include_primary: bool = True


class ResolveDiffFieldSpec(BaseModel):
    """
    Назначение:
        Декларативное сравнение одного поля в diff-policy.
    """

    field: str
    existing: str | None = None
    output: str | None = None
    normalize: Literal["none", "text", "bool"] = "none"


class ResolveDiffSpec(BaseModel):
    """
    Назначение:
        Декларативный diff-policy resolver.
    """

    class FromSinkSpec(BaseModel):
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


class ResolveMergeFieldSpec(BaseModel):
    """
    Назначение:
        Правило merge для fill_empty_from_existing.
    """

    field: str
    existing: str | None = None
    normalize: Literal["none", "text", "bool"] = "none"


class ResolveMergeSpec(BaseModel):
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


class ResolveSecretsSpec(BaseModel):
    """
    Назначение:
        Декларативная политика секретов для resolver output.
    """

    mode: Literal["none", "by_op"] = "none"
    create: list[str] = Field(default_factory=list)
    update: list[str] = Field(default_factory=list)


class ResolveLinkKeySpec(BaseModel):
    """
    Назначение:
        Декларативный ключ поиска для link-resolve.
    """

    name: str
    field: str


class ResolveLinkSpec(BaseModel):
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


class ResolveBlock(BaseModel):
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


class ResolveSpec(BaseModel):
    dataset: str
    resolve: ResolveBlock


class CacheRefreshPolicySpec(BaseModel):
    """
    Назначение:
        Политика default-поведения cache-refresh.
    """

    with_deps_default: bool = True


class DriftPolicySpec(BaseModel):
    """
    Назначение:
        Политика обработки schema drift.
    """

    mode: Literal["strict", "soft"] = "strict"
    on_hash_mismatch: Literal["fail", "rebuild"] = "fail"
    rebuild_scope: Literal["dataset", "all"] = "dataset"


class ClearPolicySpec(BaseModel):
    """
    Назначение:
        Политика cache-clear.
    """

    cascade_default: bool = False
    preserve_service_tables: bool = True
    reset_meta_on_clear: bool = True


class StatusPolicySpec(BaseModel):
    """
    Назначение:
        Политика cache-status.
    """

    enable_orphan_check: bool = True
    degraded_on_hash_mismatch: bool = True


class RetentionPolicySpec(BaseModel):
    """
    Назначение:
        Политика очистки runtime-данных cache.
    """

    pending_retention_days: int | None = None
    identity_retention_days: int | None = None
    sweep_interval_seconds: int | None = None


class CachePolicySpec(BaseModel):
    """
    Назначение:
        Глобальные политики cache runtime.
    """

    refresh: CacheRefreshPolicySpec = Field(default_factory=CacheRefreshPolicySpec)
    drift: DriftPolicySpec = Field(default_factory=DriftPolicySpec)
    clear: ClearPolicySpec = Field(default_factory=ClearPolicySpec)
    status: StatusPolicySpec = Field(default_factory=StatusPolicySpec)
    retention: RetentionPolicySpec | None = None


class CacheRegistryDatasetSpec(BaseModel):
    """
    Назначение:
        Вход dataset в cache registry.
    """

    cache_spec: str
    depends_on: list[str] = Field(default_factory=list)
    order_hint: int = 100
    allow_partial_refresh: bool = False
    enabled: bool = True


class CacheRegistrySpec(BaseModel):
    """
    Назначение:
        Реестр cache датасетов и политик.
    """

    version: int = 1
    policy: CachePolicySpec = Field(default_factory=CachePolicySpec)
    datasets: dict[str, CacheRegistryDatasetSpec] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_datasets(self) -> "CacheRegistrySpec":
        if not self.datasets:
            raise ValueError("cache.datasets must not be empty")
        return self


class CacheColumnSpec(BaseModel):
    """
    Назначение:
        Описание колонки snapshot-таблицы cache.
    """

    name: str
    type: Literal["string", "int", "float", "bool", "datetime", "json"]
    required: bool = False
    default: Any | None = None
    source: str | None = None


class CacheIndexSpec(BaseModel):
    """
    Назначение:
        Описание индекса snapshot-таблицы cache.
    """

    name: str
    fields: list[str] = Field(default_factory=list)
    unique: bool = False

    @model_validator(mode="after")
    def _validate_fields(self) -> "CacheIndexSpec":
        if not self.fields:
            raise ValueError("cache.schema.indexes[].fields must not be empty")
        return self


class CacheTableSchemaSpec(BaseModel):
    """
    Назначение:
        Схема snapshot-таблицы cache.
    """

    primary_key: str | list[str]
    columns: list[CacheColumnSpec] = Field(default_factory=list)
    indexes: list[CacheIndexSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_columns(self) -> "CacheTableSchemaSpec":
        if not self.columns:
            raise ValueError("cache.schema.columns must not be empty")
        return self


class ValueExprSpec(BaseModel):
    """
    Назначение:
        Унифицированное выражение вычисления значения в cache sync.
    """

    source: str | None = None
    sources: list[str] | None = None
    value: Any | None = None
    ops: list[OperationCall] = Field(default_factory=list)
    required: bool = False
    on_error: Literal["error", "warning", "skip", "set_null"] = "error"

    @model_validator(mode="after")
    def _validate_source(self) -> "ValueExprSpec":
        has_source = self.source is not None or bool(self.sources)
        has_const = self.value is not None
        if not has_source and not has_const:
            raise ValueError("value expression requires source/sources/value")
        return self


class SoftDeleteRuleSpec(BaseModel):
    """
    Назначение:
        Одно правило soft-delete.
    """

    type: Literal["field_equals", "field_not_null"]
    field: str
    value: Any | None = None
    normalize: list[OperationCall] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_value(self) -> "SoftDeleteRuleSpec":
        if self.type == "field_equals" and self.value is None:
            raise ValueError("soft_delete field_equals requires value")
        return self


class SoftDeleteSpec(BaseModel):
    """
    Назначение:
        Декларативная soft-delete политика.
    """

    mode: Literal["any_of", "all_of"] = "any_of"
    rules: list[SoftDeleteRuleSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_rules(self) -> "SoftDeleteSpec":
        if not self.rules:
            raise ValueError("soft_delete.rules must not be empty")
        return self


class CacheProjectionRuleSpec(BaseModel):
    """
    Назначение:
        Правило projection target payload -> cache write model.
    """

    target: str
    source: str | None = None
    sources: list[str] | None = None
    value: Any | None = None
    ops: list[OperationCall] = Field(default_factory=list)
    required: bool = False
    on_error: Literal["error", "warning", "skip", "set_null"] = "error"

    @model_validator(mode="after")
    def _validate_source(self) -> "CacheProjectionRuleSpec":
        has_source = self.source is not None or bool(self.sources)
        has_const = self.value is not None
        if not has_source and not has_const:
            raise ValueError("projection rule requires source/sources/value")
        return self


class CacheSyncSpec(BaseModel):
    """
    Назначение:
        Декларативный контракт sync target->cache.
    """

    dataset: str | None = None
    list_path: str
    report_entity: str
    item_key: ValueExprSpec
    is_deleted: ValueExprSpec | None = None
    soft_delete: SoftDeleteSpec | None = None
    projection: list[CacheProjectionRuleSpec] = Field(default_factory=list)
    include_deleted_default: bool = False

    @model_validator(mode="after")
    def _validate_projection(self) -> "CacheSyncSpec":
        if not self.projection:
            raise ValueError("cache.sync.projection must not be empty")
        if self.is_deleted is not None and self.soft_delete is not None:
            raise ValueError("cache.sync.is_deleted and cache.sync.soft_delete are mutually exclusive")
        return self


class CacheDatasetFlagsSpec(BaseModel):
    """
    Назначение:
        Служебные dataset-флаги cache.
    """

    include_deleted: bool = False


class CacheDatasetPolicyOverridesSpec(BaseModel):
    """
    Назначение:
        Dataset-level overrides поверх registry.policy.
    """

    refresh: CacheRefreshPolicySpec | None = None
    drift: DriftPolicySpec | None = None
    clear: ClearPolicySpec | None = None
    status: StatusPolicySpec | None = None
    retention: RetentionPolicySpec | None = None


class CacheDatasetSpec(BaseModel):
    """
    Назначение:
        Декларативная спецификация cache dataset.
    """

    dataset: str
    table: str
    schema_: CacheTableSchemaSpec = Field(alias="schema")
    sync: CacheSyncSpec | None = None
    flags: CacheDatasetFlagsSpec = Field(default_factory=CacheDatasetFlagsSpec)
    policy_overrides: CacheDatasetPolicyOverridesSpec | None = None

    model_config = {
        "populate_by_name": True,
    }
