"""Topology DSL compiler — topology spec to shared canonicalizer plan.

Topology-specific responsibility этого модуля ограничена trust-boundary compile
из topology YAML whitelist ops в generic compiled canonicalization contract.
Runtime execution canonicalizer-а вынесено в `transform.common`.

Responsibilities:
    - Компилировать topology canonicalization spec в shared compiled ops
    - Считать deterministic normalization version для topology contract

Out of scope:
    - Runtime canonicalization execution details
    - Построение source/target snapshot и bootstrap orchestration
    - Реальный Polars adapter и vectorized execution
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
    TopologyCanonicalizeOpSpec,
    TopologyCompactOpSpec,
    TopologyLowerOpSpec,
    TopologyRegexReplaceOpSpec,
    TopologySpec,
    TopologyTrimOpSpec,
)

CompiledTopologyCanonicalizeOp = CompiledCanonicalizeOp
CompiledTopologyCanonicalizer = CompiledCanonicalizer
CompiledTopologyPolarsExpressionPlan = CompiledPolarsExpressionPlan


@dataclass(frozen=True)
class CompiledTopologyCanonicalizerPlan:
    """Dual-form compiled contract для topology canonicalization."""

    python: CompiledTopologyCanonicalizer
    polars_expression_plan: CompiledTopologyPolarsExpressionPlan
    normalization_version: str


class TopologyDsl:
    """Скомпилировать `TopologySpec` в shared compiled canonicalizer plan."""

    def __init__(self, *, registry: OperationRegistry | None = None) -> None:
        resolved_registry = registry or OperationRegistry()
        register_core_ops(resolved_registry)
        self._registry = resolved_registry

    def compile(self, spec: TopologySpec) -> CompiledTopologyCanonicalizerPlan:
        try:
            ops = tuple(
                _compile_canonicalize_op(item)
                for item in spec.topology.canonicalization.ops
            )
            normalization_version = _build_normalization_version(ops)
            return CompiledTopologyCanonicalizerPlan(
                python=CompiledTopologyCanonicalizer(
                    ops=ops,
                    _registry=self._registry,
                ),
                polars_expression_plan=CompiledTopologyPolarsExpressionPlan(
                    ops=ops,
                    _registry=self._registry,
                ),
                normalization_version=normalization_version,
            )
        except DslLoadError:
            raise
        except Exception as exc:
            raise DslLoadError(
                code="TOPOLOGY_DSL_COMPILE_INVALID",
                message=f"Failed to compile topology DSL: {exc}",
            ) from exc


def _compile_canonicalize_op(
    spec: TopologyCanonicalizeOpSpec,
) -> CompiledCanonicalizeOp:
    if isinstance(spec, TopologyTrimOpSpec):
        return CompiledCanonicalizeOp(op="trim", scope="segment")
    if isinstance(spec, TopologyLowerOpSpec):
        return CompiledCanonicalizeOp(op="lower", scope="segment")
    if isinstance(spec, TopologyCompactOpSpec):
        return CompiledCanonicalizeOp(op="compact", scope="segments")
    if isinstance(spec, TopologyRegexReplaceOpSpec):
        return CompiledCanonicalizeOp(
            op="regex_replace",
            scope="segment",
            args=(("pattern", spec.pattern), ("repl", spec.repl)),
        )
    raise DslLoadError(
        code="TOPOLOGY_DSL_COMPILE_INVALID",
        message=f"Unsupported topology canonicalizer op spec: {type(spec).__name__}",
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
