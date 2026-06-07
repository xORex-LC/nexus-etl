"""Shared canonicalization DSL compiler — spec to compiled runtime plan.

Модуль компилирует generic canonicalization spec в transport-neutral runtime
plan, который затем может исполняться через Python path или infra-level
Polars adapter.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.transform.common import (
    CompiledCanonicalizeOp,
    CompiledCanonicalizer,
    CompiledPolarsExpressionPlan,
)
from connector.domain.transform_dsl.specs import (
    CanonicalizationSpec,
    CanonicalizeOpSpec,
    CompactOpSpec,
    LowerOpSpec,
    RegexReplaceOpSpec,
    TrimOpSpec,
)


@dataclass(frozen=True)
class CompiledCanonicalizerPlan:
    """Dual-form compiled contract для shared canonicalization spec."""

    python: CompiledCanonicalizer
    polars_expression_plan: CompiledPolarsExpressionPlan
    normalization_version: str


class CanonicalizationDsl:
    """Скомпилировать `CanonicalizationSpec` в shared canonicalizer plan."""

    def __init__(self, *, registry: OperationRegistry | None = None) -> None:
        if registry is None:
            resolved_registry = OperationRegistry()
            register_core_ops(resolved_registry)
        else:
            resolved_registry = registry
        self._registry = resolved_registry

    def compile(self, spec: CanonicalizationSpec) -> CompiledCanonicalizerPlan:
        try:
            ops = tuple(_compile_canonicalize_op(item) for item in spec.ops)
            normalization_version = _build_normalization_version(ops)
            return CompiledCanonicalizerPlan(
                python=CompiledCanonicalizer(
                    ops=ops,
                    _registry=self._registry,
                ),
                polars_expression_plan=CompiledPolarsExpressionPlan(
                    ops=ops,
                    _registry=self._registry,
                ),
                normalization_version=normalization_version,
            )
        except DslLoadError:
            raise
        except Exception as exc:
            raise DslLoadError(
                code="CANONICALIZATION_DSL_COMPILE_INVALID",
                message=f"Failed to compile canonicalization DSL: {exc}",
            ) from exc


def _compile_canonicalize_op(spec: CanonicalizeOpSpec) -> CompiledCanonicalizeOp:
    if isinstance(spec, TrimOpSpec):
        return CompiledCanonicalizeOp(op="trim", scope="segment")
    if isinstance(spec, LowerOpSpec):
        return CompiledCanonicalizeOp(op="lower", scope="segment")
    if isinstance(spec, CompactOpSpec):
        return CompiledCanonicalizeOp(op="compact", scope="segments")
    if isinstance(spec, RegexReplaceOpSpec):
        return CompiledCanonicalizeOp(
            op="regex_replace",
            scope="segment",
            args=(("pattern", spec.pattern), ("repl", spec.repl)),
        )
    raise DslLoadError(
        code="CANONICALIZATION_DSL_COMPILE_INVALID",
        message=f"Unsupported canonicalizer op spec: {type(spec).__name__}",
    )


def _build_normalization_version(
    ops: tuple[CompiledCanonicalizeOp, ...],
) -> str:
    payload = [
        {
            "op": item.op,
            "scope": item.scope,
            "args": list(item.args),
        }
        for item in ops
    ]
    serialized = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
