from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connector.datasets.cache_sync import CacheSyncAdapterProtocol
from connector.domain.dsl.engine import TransformationEngine
from connector.domain.dsl.specs import (
    CacheDatasetSpec,
    CacheProjectionRuleSpec,
    CacheSyncSpec,
    SoftDeleteRuleSpec,
    ValueExprSpec,
)


@dataclass(frozen=True)
class DslCacheSyncAdapter(CacheSyncAdapterProtocol):
    """
    Универсальный cache sync adapter, управляемый DSL.
    """

    dataset: str
    list_path: str
    report_entity: str
    include_deleted_default: bool
    sync_spec: CacheSyncSpec
    dataset_spec: CacheDatasetSpec
    engine: TransformationEngine

    def get_item_key(self, raw_item: dict[str, Any]) -> str:
        value = _eval_value_expr(
            raw_item=raw_item,
            expr=self.sync_spec.item_key,
            engine=self.engine,
        )
        if value is None or (isinstance(value, str) and value.strip() == ""):
            raise ValueError("cache sync item_key is empty")
        return str(value)

    def is_deleted(self, raw_item: dict[str, Any]) -> bool:
        if self.sync_spec.soft_delete is not None:
            return _eval_soft_delete(raw_item, self.sync_spec.soft_delete.mode, self.sync_spec.soft_delete.rules, self.engine)
        expr = self.sync_spec.is_deleted
        if expr is None:
            return False
        value = _eval_value_expr(raw_item=raw_item, expr=expr, engine=self.engine)
        if value is None:
            return False
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        normalized = str(value).strip().lower()
        return normalized in {"1", "true", "yes", "y"}

    def map_target_to_cache(self, raw_item: dict[str, Any]) -> dict[str, Any]:
        mapped: dict[str, Any] = {}
        for rule in self.sync_spec.projection:
            value = _eval_projection_rule(raw_item=raw_item, rule=rule, engine=self.engine)
            if value is None:
                if rule.required:
                    raise ValueError(f"required cache field is empty: {rule.target}")
                mapped[rule.target] = None
                continue
            mapped[rule.target] = value
        return mapped


def build_dsl_cache_sync_adapter(
    *,
    dataset_spec: CacheDatasetSpec,
    sync_spec: CacheSyncSpec,
    engine: TransformationEngine | None = None,
) -> DslCacheSyncAdapter:
    effective_engine = engine or TransformationEngine.with_core_ops()
    return DslCacheSyncAdapter(
        dataset=dataset_spec.dataset,
        list_path=sync_spec.list_path,
        report_entity=sync_spec.report_entity,
        include_deleted_default=sync_spec.include_deleted_default,
        sync_spec=sync_spec,
        dataset_spec=dataset_spec,
        engine=effective_engine,
    )


def _eval_projection_rule(
    *,
    raw_item: dict[str, Any],
    rule: CacheProjectionRuleSpec,
    engine: TransformationEngine,
) -> Any:
    expr = ValueExprSpec(
        source=rule.source,
        sources=rule.sources,
        value=rule.value,
        ops=rule.ops,
        required=rule.required,
        on_error=rule.on_error,
    )
    return _eval_value_expr(raw_item=raw_item, expr=expr, engine=engine)


def _eval_value_expr(
    *,
    raw_item: dict[str, Any],
    expr: ValueExprSpec,
    engine: TransformationEngine,
) -> Any:
    current = _read_expr_source(raw_item, expr)
    if expr.ops:
        result = engine.apply(current, expr.ops)
        if result.issues:
            if expr.on_error == "error":
                message = "; ".join(issue.message for issue in result.issues)
                raise ValueError(message)
            return None
        current = result.value

    if expr.required and _is_empty(current):
        raise ValueError("required value is empty")
    return current


def _eval_soft_delete(
    raw_item: dict[str, Any],
    mode: str,
    rules: list[SoftDeleteRuleSpec],
    engine: TransformationEngine,
) -> bool:
    matches: list[bool] = []
    for rule in rules:
        raw_value = _read_path(raw_item, rule.field)
        value = raw_value
        if rule.normalize:
            normalized = engine.apply(raw_value, rule.normalize)
            if normalized.issues:
                value = raw_value
            else:
                value = normalized.value
        if rule.type == "field_not_null":
            match = not _is_null_like(value)
        else:
            expected = rule.value
            if rule.normalize:
                normalized_expected = engine.apply(expected, rule.normalize)
                if not normalized_expected.issues:
                    expected = normalized_expected.value
            match = value == expected
        matches.append(match)

    if not matches:
        return False
    if mode == "all_of":
        return all(matches)
    return any(matches)


def _read_expr_source(raw_item: dict[str, Any], expr: ValueExprSpec) -> Any:
    if expr.value is not None:
        return expr.value
    if expr.source is not None:
        return _read_path(raw_item, expr.source)
    if expr.sources:
        return [_read_path(raw_item, path) for path in expr.sources]
    return None


def _read_path(data: dict[str, Any], path: str) -> Any:
    if "." not in path:
        return data.get(path)
    current: Any = data
    for part in path.split("."):
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _is_empty(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def _is_null_like(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        normalized = value.strip().lower()
        return normalized in {"", "null", "none"}
    return False
