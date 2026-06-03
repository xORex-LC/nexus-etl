"""Shared canonicalization runtime — compiled ops and execution paths.

Нижний reusable слой канонизации для разных transform-consumer-ов. Модуль
содержит generic compiled contract и единый runtime executor поверх
зарегистрированных DSL-операций.

Зона ответственности:
    - Хранить compiled canonicalization ops в transport-neutral форме
    - Выполнять scalar/segments canonicalization через OperationRegistry
    - Давать dual-form runtime contract без topology/cache-specific семантики

Вне области ответственности:
    - Компиляция конкретного YAML DSL в canonicalization ops
    - Match/resolve/topology consumer orchestration
    - Реальный Polars adapter и vectorized execution
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.registry import OperationRegistry

CanonicalizeOpScope = Literal["segment", "segments"]


@dataclass(frozen=True)
class CompiledCanonicalizeOp:
    """Один compiled шаг generic canonicalization pipeline."""

    op: str
    scope: CanonicalizeOpScope
    args: tuple[tuple[str, str], ...] = ()

    def args_dict(self) -> dict[str, str]:
        return dict(self.args)


@dataclass(frozen=True)
class CompiledCanonicalizer:
    """Python/runtime форма generic canonicalizer-а."""

    ops: tuple[CompiledCanonicalizeOp, ...]
    _registry: OperationRegistry

    def canonicalize_segments(self, segments: tuple[str, ...]) -> tuple[str, ...]:
        """Канонизировать ordered segments через shared runtime path."""

        return apply_compiled_canonicalizer_ops(
            ops=self.ops,
            registry=self._registry,
            segments=segments,
        )

    def canonicalize_scalar(self, value: str) -> str:
        """Канонизировать одно scalar значение через segment-aware pipeline."""

        canonical_segments = self.canonicalize_segments((value,))
        if not canonical_segments:
            return ""
        return canonical_segments[0]


@dataclass(frozen=True)
class CompiledPolarsExpressionPlan:
    """Декларативная vector-friendly форма canonicalizer-а.

    На текущем этапе это placeholder runtime path, который использует тот же
    shared executor, что и python-форма. Позже сюда может быть подключён
    реальный Polars adapter без смены compile contract.
    """

    ops: tuple[CompiledCanonicalizeOp, ...]
    _registry: OperationRegistry

    def apply_to_segments(self, segments: tuple[str, ...]) -> tuple[str, ...]:
        """Применить canonicalization к segments через shared placeholder path."""

        return apply_compiled_canonicalizer_ops(
            ops=self.ops,
            registry=self._registry,
            segments=segments,
        )


def apply_compiled_canonicalizer_ops(
    *,
    ops: tuple[CompiledCanonicalizeOp, ...],
    registry: OperationRegistry,
    segments: tuple[str, ...],
) -> tuple[str, ...]:
    """Исполнить compiled canonicalizer через общий DSL op-path.

    Args:
        ops: Ordered compiled canonicalization steps.
        registry: Реестр core DSL operations.
        segments: Ordered textual segments для канонизации.

    Returns:
        Tuple canonicalized segments.

    Raises:
        DslLoadError: Если compiled step ссылается на неизвестную операцию.
    """

    current: tuple[str, ...] = tuple(str(segment) for segment in segments)
    for step in ops:
        operation = registry.get(step.op)
        if operation is None:
            raise DslLoadError(
                code="TOPOLOGY_DSL_COMPILE_INVALID",
                message=f"Unknown topology canonicalizer operation: {step.op}",
            )
        if step.scope == "segment":
            current = tuple(
                "" if value is None else str(value)
                for value in (
                    operation.func(segment, **step.args_dict()) for segment in current
                )
            )
            continue
        compacted = operation.func(list(current), **step.args_dict())
        current = tuple("" if value is None else str(value) for value in compacted)
    return current
