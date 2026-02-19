"""
Назначение:
    Cache DSL спецификации: registry, dataset, sync, schema, policies.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, Field, model_validator

from connector.domain.dsl.specs._base import DslBaseModel, OperationCall


# ========== POLICIES ==========


class CacheRefreshPolicySpec(DslBaseModel):
    """
    Назначение:
        Политика default-поведения cache-refresh.
    """

    with_deps_default: bool = True


class DriftPolicySpec(DslBaseModel):
    """
    Назначение:
        Политика обработки schema drift.
    """

    mode: Literal["strict", "soft"] = "strict"
    on_hash_mismatch: Literal["fail", "rebuild"] = "fail"
    rebuild_scope: Literal["dataset", "all"] = "dataset"


class ClearPolicySpec(DslBaseModel):
    """
    Назначение:
        Политика cache-clear.
    """

    cascade_default: bool = False
    preserve_service_tables: bool = True
    reset_meta_on_clear: bool = True


class StatusPolicySpec(DslBaseModel):
    """
    Назначение:
        Политика cache-status.
    """

    enable_orphan_check: bool = True
    degraded_on_hash_mismatch: bool = True


class RetentionPolicySpec(DslBaseModel):
    """
    Назначение:
        Политика очистки runtime-данных cache.
    """

    pending_retention_days: int | None = None
    identity_retention_days: int | None = None
    sweep_interval_seconds: int | None = None


class CachePolicySpec(DslBaseModel):
    """
    Назначение:
        Глобальные политики cache runtime.
    """

    refresh: CacheRefreshPolicySpec = Field(default_factory=CacheRefreshPolicySpec)
    drift: DriftPolicySpec = Field(default_factory=DriftPolicySpec)
    clear: ClearPolicySpec = Field(default_factory=ClearPolicySpec)
    status: StatusPolicySpec = Field(default_factory=StatusPolicySpec)
    retention: RetentionPolicySpec | None = None


# ========== REGISTRY ==========


class CacheRegistryDatasetSpec(DslBaseModel):
    """
    Назначение:
        Вход dataset в cache registry.
    """

    cache_spec: str
    depends_on: list[str] = Field(default_factory=list)
    order_hint: int = 100
    allow_partial_refresh: bool = False
    enabled: bool = True


class CacheRegistrySpec(DslBaseModel):
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


# ========== SCHEMA ==========


class CacheColumnSpec(DslBaseModel):
    """
    Назначение:
        Описание колонки snapshot-таблицы cache.
    """

    name: str
    type: Literal["string", "int", "float", "bool", "datetime", "json"]
    required: bool = False
    default: Any | None = None
    source: str | None = None


class CacheIndexSpec(DslBaseModel):
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


class CacheTableSchemaSpec(DslBaseModel):
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


# ========== SYNC ==========


class ValueExprSpec(DslBaseModel):
    """
    Назначение:
        Унифицированное выражение вычисления значения в cache sync.
    """

    source: str | None = None
    sources: list[str] | None = None
    value: Any | None = None
    ops: list[OperationCall] = Field(default_factory=list)
    required: bool = False
    on_error: Literal["error", "warn", "skip", "set_null"] = "error"

    @model_validator(mode="after")
    def _validate_source(self) -> "ValueExprSpec":
        has_source = self.source is not None or bool(self.sources)
        has_const = self.value is not None
        if not has_source and not has_const:
            raise ValueError("value expression requires source/sources/value")
        return self


class SoftDeleteRuleSpec(DslBaseModel):
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


class SoftDeleteSpec(DslBaseModel):
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


class CacheProjectionRuleSpec(DslBaseModel):
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
    on_error: Literal["error", "warn", "skip", "set_null"] = "error"

    @model_validator(mode="after")
    def _validate_source(self) -> "CacheProjectionRuleSpec":
        has_source = self.source is not None or bool(self.sources)
        has_const = self.value is not None
        if not has_source and not has_const:
            raise ValueError("projection rule requires source/sources/value")
        return self


class CacheSyncSpec(DslBaseModel):
    """
    Назначение:
        Декларативный контракт sync target->cache.
    """

    dataset: str | None = None
    list_operation_alias: str = Field(
        validation_alias=AliasChoices("list_operation_alias", "list_path"),
    )
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


# ========== DATASET ==========


class CacheDatasetFlagsSpec(DslBaseModel):
    """
    Назначение:
        Служебные dataset-флаги cache.
    """

    include_deleted: bool = False


class CacheDatasetPolicyOverridesSpec(DslBaseModel):
    """
    Назначение:
        Dataset-level overrides поверх registry.policy.
    """

    refresh: CacheRefreshPolicySpec | None = None
    drift: DriftPolicySpec | None = None
    clear: ClearPolicySpec | None = None
    status: StatusPolicySpec | None = None
    retention: RetentionPolicySpec | None = None


class CacheDatasetSpec(DslBaseModel):
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
        "extra": "forbid",
        "populate_by_name": True,
    }
