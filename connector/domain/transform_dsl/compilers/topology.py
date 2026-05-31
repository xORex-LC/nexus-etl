"""
Назначение:
    TopologyDsl: компиляция topology-spec в shared canonicalizer plan.

Граница ответственности:
    - Owns: trust-boundary compile topology whitelist-ops в dual-form contract.
    - Does NOT: строить source/target snapshot, читать Polars или выполнять bootstrap orchestration.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.transform_dsl.specs import (
    TopologyCanonicalizeOpSpec,
    TopologyCompactOpSpec,
    TopologyLowerOpSpec,
    TopologyRegexReplaceOpSpec,
    TopologySpec,
    TopologyTrimOpSpec,
)

TopologyOpScope = Literal["segment", "segments"]


@dataclass(frozen=True)
class CompiledTopologyCanonicalizeOp:
    """
    Назначение:
        Скомпилированный шаг topology canonicalizer-а.
    """

    op: str
    scope: TopologyOpScope
    args: tuple[tuple[str, str], ...] = ()

    def args_dict(self) -> dict[str, str]:
        return dict(self.args)


@dataclass(frozen=True)
class CompiledTopologyCanonicalizer:
    """
    Назначение:
        Python-форма topology canonicalizer-а для runtime lookup/build.
    """

    ops: tuple[CompiledTopologyCanonicalizeOp, ...]
    _registry: OperationRegistry

    def canonicalize_segments(self, segments: tuple[str, ...]) -> tuple[str, ...]:
        current: tuple[str, ...] = tuple(str(segment) for segment in segments)
        for step in self.ops:
            operation = self._registry.get(step.op)
            if operation is None:
                raise DslLoadError(
                    code="TOPOLOGY_DSL_COMPILE_INVALID",
                    message=f"Unknown topology canonicalizer operation: {step.op}",
                )
            if step.scope == "segment":
                current = tuple(
                    "" if value is None else str(value)
                    for value in (
                        operation.func(segment, **step.args_dict())
                        for segment in current
                    )
                )
                continue
            compacted = operation.func(list(current), **step.args_dict())
            current = tuple("" if value is None else str(value) for value in compacted)
        return current


@dataclass(frozen=True)
class CompiledTopologyPolarsExpressionPlan:
    """
    Назначение:
        Декларативная Polars-friendly форма topology canonicalizer-а.

    Примечание:
        На Stage B это ещё не реальный `pl.Expr` adapter. План хранит
        детерминированную последовательность шагов, которую later infra-adapter
        сможет превратить в vectorized expression pipeline без повторного парсинга YAML.
    """

    ops: tuple[CompiledTopologyCanonicalizeOp, ...]

    def apply_to_segments(self, segments: tuple[str, ...]) -> tuple[str, ...]:
        current: tuple[str, ...] = tuple(str(segment) for segment in segments)
        for step in self.ops:
            if step.op == "trim":
                current = tuple(_segment_trim(segment) for segment in current)
            elif step.op == "lower":
                current = tuple(segment.lower() for segment in current)
            elif step.op == "regex_replace":
                args = step.args_dict()
                current = tuple(
                    _segment_regex_replace(
                        segment,
                        pattern=args["pattern"],
                        repl=args["repl"],
                    )
                    for segment in current
                )
            elif step.op == "compact":
                current = tuple(
                    segment for segment in current if str(segment).strip() != ""
                )
            else:
                raise DslLoadError(
                    code="TOPOLOGY_DSL_COMPILE_INVALID",
                    message=f"Unsupported topology polars-expression op: {step.op}",
                )
        return current


@dataclass(frozen=True)
class CompiledTopologyCanonicalizerPlan:
    """
    Назначение:
        Dual-form compiled contract для topology canonicalization.
    """

    python: CompiledTopologyCanonicalizer
    polars_expression_plan: CompiledTopologyPolarsExpressionPlan
    normalization_version: str


class TopologyDsl:
    """
    Назначение:
        Скомпилировать `TopologySpec` в shared compiled canonicalizer plan.
    """

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
                polars_expression_plan=CompiledTopologyPolarsExpressionPlan(ops=ops),
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
) -> CompiledTopologyCanonicalizeOp:
    if isinstance(spec, TopologyTrimOpSpec):
        return CompiledTopologyCanonicalizeOp(op="trim", scope="segment")
    if isinstance(spec, TopologyLowerOpSpec):
        return CompiledTopologyCanonicalizeOp(op="lower", scope="segment")
    if isinstance(spec, TopologyCompactOpSpec):
        return CompiledTopologyCanonicalizeOp(op="compact", scope="segments")
    if isinstance(spec, TopologyRegexReplaceOpSpec):
        return CompiledTopologyCanonicalizeOp(
            op="regex_replace",
            scope="segment",
            args=(("pattern", spec.pattern), ("repl", spec.repl)),
        )
    raise DslLoadError(
        code="TOPOLOGY_DSL_COMPILE_INVALID",
        message=f"Unsupported topology canonicalizer op spec: {type(spec).__name__}",
    )


def _build_normalization_version(
    ops: tuple[CompiledTopologyCanonicalizeOp, ...],
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


def _segment_trim(value: str) -> str:
    return " ".join(str(value).split())


def _segment_regex_replace(value: str, *, pattern: str, repl: str) -> str:
    import re

    return re.sub(pattern, repl, value)
