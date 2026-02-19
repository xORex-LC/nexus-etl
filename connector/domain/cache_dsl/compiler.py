"""
Назначение:
    CacheDsl: компиляция Cache DSL Spec в CacheDslRuntime.
    Compiled models: CacheDslRuntime, CacheDslRuntimePolicy.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json

from connector.domain.cache_core.cache_dependency_graph import CacheDependencyGraph
from connector.domain.dsl.issues import DslLoadError
from connector.domain.cache_dsl.build_options import CacheDslBuildOptions
from connector.domain.cache_dsl.specs import (
    CacheDatasetSpec,
    CacheRegistrySpec,
    CacheSyncSpec,
)
from connector.domain.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.ports.cache.models import CacheSpec, FieldSpec


# ========== COMPILED MODELS ==========


@dataclass(frozen=True)
class CacheDslRuntimePolicy:
    """
    Назначение:
        Скомпилированные глобальные политики cache runtime.
    """

    refresh_with_deps_default: bool
    clear_cascade_default: bool
    preserve_service_tables: bool
    reset_meta_on_clear: bool
    drift_mode: str
    drift_on_hash_mismatch: str
    drift_rebuild_scope: str
    status_enable_orphan_check: bool
    status_degraded_on_hash_mismatch: bool
    pending_retention_days: int | None
    identity_retention_days: int | None
    sweep_interval_seconds: int | None


@dataclass(frozen=True)
class CacheDslRuntime:
    """
    Назначение:
        Скомпилированный runtime bundle для cache.
    """

    cache_specs: tuple[CacheSpec, ...]
    sync_specs: dict[str, CacheSyncSpec]
    dependency_graph: CacheDependencyGraph
    schema_hashes: dict[str, str]
    sync_hashes: dict[str, str]
    policy: CacheDslRuntimePolicy


# ========== COMPILER ==========


class CacheDsl:
    """
    Назначение:
        Явный DSL-компилятор cache-runtime (канонический вход compile-процесса).
    """

    def __init__(self, *, options: CacheDslBuildOptions | None = None) -> None:
        self.options = options or CacheDslBuildOptions()

    def compile_runtime(
        self,
        *,
        registry_spec: CacheRegistrySpec,
        dataset_specs: dict[str, CacheDatasetSpec],
    ) -> CacheDslRuntime:
        return compile_cache_runtime(
            registry_spec=registry_spec,
            dataset_specs=dataset_specs,
            options=self.options,
        )


def compile_cache_runtime(
    *,
    registry_spec: CacheRegistrySpec,
    dataset_specs: dict[str, CacheDatasetSpec],
    options: CacheDslBuildOptions | None = None,
) -> CacheDslRuntime:
    """
    Назначение:
        Скомпилировать cache DSL в runtime-конфигурацию.
    """
    enabled_entries = {
        name: entry for name, entry in registry_spec.datasets.items() if entry.enabled
    }
    if not enabled_entries:
        raise DslLoadError(
            code="CACHE_DSL_REGISTRY_INVALID",
            message="No enabled datasets in cache registry",
        )

    compile_options = options or CacheDslBuildOptions()
    _validate_dataset_specs(enabled_entries, dataset_specs)
    dependencies = _build_dependencies(enabled_entries, compile_options)
    dataset_order = _build_dataset_order(enabled_entries)

    try:
        graph = CacheDependencyGraph(dataset_order, dependencies=dependencies)
    except ValueError as exc:
        msg = str(exc)
        code = "CACHE_DSL_DEP_CYCLE" if "cycle" in msg.lower() else "CACHE_DSL_DEP_MISSING"
        raise DslLoadError(code=code, message=msg) from exc

    compiled_specs: list[CacheSpec] = []
    sync_specs: dict[str, CacheSyncSpec] = {}
    schema_hashes: dict[str, str] = {}
    sync_hashes: dict[str, str] = {}
    ops_registry: OperationRegistry | None = None
    if compile_options.fail_on_unknown_ops:
        ops_registry = OperationRegistry()
        register_core_ops(ops_registry)

    for dataset in graph.refresh_order():
        spec = dataset_specs[dataset]
        _validate_semantics(dataset, spec, compile_options, ops_registry=ops_registry)
        compiled = _compile_cache_spec(dataset, spec)
        compiled_specs.append(compiled)
        schema_hashes[dataset] = build_schema_hash(compiled)
        if spec.sync is not None:
            sync_spec = spec.sync
            if sync_spec.dataset is None:
                sync_spec = sync_spec.model_copy(update={"dataset": dataset})
            sync_specs[dataset] = sync_spec
            sync_hashes[dataset] = build_sync_hash(sync_spec)

    policy = _compile_policy(registry_spec)
    return CacheDslRuntime(
        cache_specs=tuple(compiled_specs),
        sync_specs=sync_specs,
        dependency_graph=graph,
        schema_hashes=schema_hashes,
        sync_hashes=sync_hashes,
        policy=policy,
    )


def build_schema_hash(spec: CacheSpec) -> str:
    """
    Назначение:
        Детерминированный hash только по schema-части cache spec.
    """
    payload = {
        "dataset": spec.dataset,
        "table": spec.table,
        "primary_key": list(spec.primary_key),
        "fields": [
            {
                "name": field.name,
                "type": field.type,
                "nullable": field.nullable,
                "source": field.source,
            }
            for field in spec.fields
        ],
        "unique_indexes": [list(idx) for idx in spec.unique_indexes],
        "indexes": [list(idx) for idx in spec.indexes],
    }
    return _hash_payload(payload)


def build_sync_hash(sync_spec: CacheSyncSpec) -> str:
    """
    Назначение:
        Детерминированный hash sync-части (status/диагностика).
    """
    payload = sync_spec.model_dump(mode="json", by_alias=True)
    return _hash_payload(payload)


# ========== PRIVATE HELPERS ==========


def _hash_payload(payload: dict) -> str:
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return sha256(normalized.encode("utf-8")).hexdigest()


def _compile_cache_spec(dataset: str, spec: CacheDatasetSpec) -> CacheSpec:
    primary_key = spec.schema_.primary_key
    if isinstance(primary_key, str):
        pk_tuple = (primary_key,)
    else:
        pk_tuple = tuple(primary_key)

    fields = tuple(
        FieldSpec(
            name=column.name,
            type=column.type,
            nullable=not column.required,
            source=column.source,
        )
        for column in spec.schema_.columns
    )
    unique_indexes: list[tuple[str, ...]] = []
    indexes: list[tuple[str, ...]] = []
    for idx in spec.schema_.indexes:
        columns = tuple(idx.fields)
        if idx.unique:
            unique_indexes.append(columns)
        else:
            indexes.append(columns)

    return CacheSpec(
        dataset=dataset,
        table=spec.table,
        primary_key=pk_tuple,
        fields=fields,
        unique_indexes=tuple(unique_indexes),
        indexes=tuple(indexes),
    )


def _compile_policy(registry_spec: CacheRegistrySpec) -> CacheDslRuntimePolicy:
    retention = registry_spec.policy.retention
    return CacheDslRuntimePolicy(
        refresh_with_deps_default=registry_spec.policy.refresh.with_deps_default,
        clear_cascade_default=registry_spec.policy.clear.cascade_default,
        preserve_service_tables=registry_spec.policy.clear.preserve_service_tables,
        reset_meta_on_clear=registry_spec.policy.clear.reset_meta_on_clear,
        drift_mode=registry_spec.policy.drift.mode,
        drift_on_hash_mismatch=registry_spec.policy.drift.on_hash_mismatch,
        drift_rebuild_scope=registry_spec.policy.drift.rebuild_scope,
        status_enable_orphan_check=registry_spec.policy.status.enable_orphan_check,
        status_degraded_on_hash_mismatch=registry_spec.policy.status.degraded_on_hash_mismatch,
        pending_retention_days=retention.pending_retention_days if retention else None,
        identity_retention_days=retention.identity_retention_days if retention else None,
        sweep_interval_seconds=retention.sweep_interval_seconds if retention else None,
    )


def _validate_dataset_specs(
    enabled_entries: dict[str, object],
    dataset_specs: dict[str, CacheDatasetSpec],
) -> None:
    missing = sorted(set(enabled_entries.keys()) - set(dataset_specs.keys()))
    if missing:
        raise DslLoadError(
            code="CACHE_DSL_SPEC_INVALID",
            message=f"Missing cache dataset specs for: {missing}",
            details={"missing_datasets": missing},
        )

    for dataset, spec in dataset_specs.items():
        if dataset not in enabled_entries:
            continue
        if spec.dataset != dataset:
            raise DslLoadError(
                code="CACHE_DSL_SPEC_INVALID",
                message=f"Spec dataset mismatch: key={dataset}, spec.dataset={spec.dataset}",
                details={"dataset": dataset},
            )


def _build_dependencies(
    enabled_entries: dict[str, object],
    options: CacheDslBuildOptions,
) -> dict[str, tuple[str, ...]]:
    result: dict[str, tuple[str, ...]] = {}
    enabled_set = set(enabled_entries.keys())
    for dataset, entry in enabled_entries.items():
        deps = tuple(dict.fromkeys(entry.depends_on))
        unknown = [dep for dep in deps if dep not in enabled_set]
        if unknown:
            if options.fail_on_unknown_dependencies:
                raise DslLoadError(
                    code="CACHE_DSL_DEP_MISSING",
                    message=f"Dataset '{dataset}' has unknown dependencies: {unknown}",
                    details={"dataset": dataset, "unknown_dependencies": unknown},
                )
            deps = tuple(dep for dep in deps if dep in enabled_set)
        result[dataset] = deps
    return result


def _build_dataset_order(enabled_entries: dict[str, object]) -> tuple[str, ...]:
    ordered = sorted(
        enabled_entries.items(),
        key=lambda item: (item[1].order_hint, item[0]),
    )
    return tuple(name for name, _ in ordered)


def _validate_semantics(
    dataset: str,
    spec: CacheDatasetSpec,
    options: CacheDslBuildOptions,
    *,
    ops_registry: OperationRegistry | None = None,
) -> None:
    column_names = [col.name for col in spec.schema_.columns]
    duplicates = sorted({name for name in column_names if column_names.count(name) > 1})
    if duplicates:
        raise DslLoadError(
            code="CACHE_DSL_SPEC_INVALID",
            message=f"Duplicate columns in cache schema '{dataset}': {duplicates}",
            details={"dataset": dataset, "columns": duplicates},
        )
    known_columns = set(column_names)

    primary_key = spec.schema_.primary_key
    pk_fields = [primary_key] if isinstance(primary_key, str) else list(primary_key)
    for field in pk_fields:
        if field not in known_columns:
            if options.fail_on_unknown_pk_fields:
                raise DslLoadError(
                    code="CACHE_DSL_SPEC_INVALID",
                    message=f"Primary key field '{field}' is not declared in columns",
                    details={"dataset": dataset, "field": field},
                )

    for idx in spec.schema_.indexes:
        unknown = [field for field in idx.fields if field not in known_columns]
        if unknown:
            if options.fail_on_unknown_index_fields:
                raise DslLoadError(
                    code="CACHE_DSL_SPEC_INVALID",
                    message=f"Index '{idx.name}' references unknown fields: {unknown}",
                    details={"dataset": dataset, "index": idx.name, "fields": unknown},
                )

    if spec.sync is None:
        return
    if options.fail_on_unknown_ops and ops_registry is not None:
        _validate_sync_ops_known(dataset, spec.sync, ops_registry)

    if options.forbid_is_deleted_and_soft_delete_together:
        if spec.sync.is_deleted is not None and spec.sync.soft_delete is not None:
            raise DslLoadError(
                code="CACHE_DSL_SPEC_INVALID",
                message="cache.sync.is_deleted and cache.sync.soft_delete are mutually exclusive",
                details={"dataset": dataset},
            )

    if spec.sync.dataset is not None and spec.sync.dataset != dataset:
        if options.require_sync_dataset_match:
            raise DslLoadError(
                code="CACHE_DSL_SPEC_INVALID",
                message=f"cache.sync.dataset mismatch: expected '{dataset}', got '{spec.sync.dataset}'",
                details={"dataset": dataset},
            )

    projection_targets = [rule.target for rule in spec.sync.projection]
    dup_targets = sorted({name for name in projection_targets if projection_targets.count(name) > 1})
    if dup_targets:
        if options.fail_on_duplicate_projection_targets:
            raise DslLoadError(
                code="CACHE_DSL_SPEC_INVALID",
                message=f"cache.sync.projection has duplicate targets: {dup_targets}",
                details={"dataset": dataset, "targets": dup_targets},
            )

    unknown_targets = sorted({target for target in projection_targets if target not in known_columns})
    if unknown_targets:
        if options.fail_on_unknown_projection_targets:
            raise DslLoadError(
                code="CACHE_DSL_SPEC_INVALID",
                message=f"cache.sync.projection references unknown target columns: {unknown_targets}",
                details={"dataset": dataset, "targets": unknown_targets},
            )


def _validate_sync_ops_known(
    dataset: str,
    sync_spec: CacheSyncSpec,
    registry: OperationRegistry,
) -> None:
    unknown_ops: list[dict[str, object]] = []
    for context, calls in _iter_sync_operation_calls(sync_spec):
        for step, op_call in enumerate(calls):
            if registry.get(op_call.op) is None:
                unknown_ops.append(
                    {
                        "op": op_call.op,
                        "context": context,
                        "step": step,
                    }
                )
    if unknown_ops:
        unknown_names = sorted({str(item["op"]) for item in unknown_ops})
        raise DslLoadError(
            code="DSL_OP_UNKNOWN",
            message=f"Unknown DSL operations in cache sync spec '{dataset}': {unknown_names}",
            details={
                "dataset": dataset,
                "unknown_ops": unknown_ops,
            },
        )


def _iter_sync_operation_calls(sync_spec: CacheSyncSpec):
    yield "cache.sync.item_key.ops", sync_spec.item_key.ops
    if sync_spec.is_deleted is not None:
        yield "cache.sync.is_deleted.ops", sync_spec.is_deleted.ops
    if sync_spec.soft_delete is not None:
        for idx, rule in enumerate(sync_spec.soft_delete.rules):
            yield f"cache.sync.soft_delete.rules[{idx}].normalize", rule.normalize
    for idx, rule in enumerate(sync_spec.projection):
        yield f"cache.sync.projection[{idx}].ops", rule.ops
