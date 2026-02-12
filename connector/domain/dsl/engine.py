"""
Назначение:
    Универсальный движок трансформаций: применяет операции DSL к значениям.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from connector.domain.dsl.issues import DslIssue, DslSeverity
from connector.domain.dsl.registry import OperationRegistry
from connector.domain.dsl.specs import OperationCall


@dataclass(frozen=True)
class EngineResult:
    """
    Назначение:
        Результат применения операций DSL.
    """

    value: Any
    issues: tuple[DslIssue, ...] = field(default_factory=tuple)


class TransformationEngine:
    """
    Назначение/ответственность:
        Применяет последовательность операций DSL к значению.
    """

    def __init__(self, registry: OperationRegistry) -> None:
        self.registry = registry

    @classmethod
    def with_core_ops(cls) -> "TransformationEngine":
        """
        Назначение:
            Быстрый конструктор движка с базовым реестром операций.
        """
        from connector.domain.dsl.registry import OperationRegistry, register_core_ops

        registry = OperationRegistry()
        register_core_ops(registry)
        return cls(registry)

    def apply(self, value: Any, ops: Iterable[OperationCall]) -> EngineResult:
        """
        Назначение:
            Применить операции DSL к значению.

        Алгоритм:
            - Каждая операция применяется последовательно.
            - Ошибки фиксируются как DslIssue, дальнейшие операции не выполняются.
        """

        current = value
        issues: list[DslIssue] = []
        for step, op_call in enumerate(ops):
            op = self.registry.get(op_call.op)
            if op is None:
                issues.append(
                    DslIssue(
                        code="DSL_OP_UNKNOWN",
                        message=f"Unknown operation '{op_call.op}'",
                        severity=DslSeverity.ERROR,
                        details={"op": op_call.op, "step": step},
                    )
                )
                break
            try:
                current = op.func(current, **op_call.args)
            except Exception as exc:  # noqa: BLE001
                issues.append(
                    DslIssue(
                        code="DSL_OP_FAILED",
                        message=f"Operation '{op_call.op}' failed: {exc}",
                        severity=DslSeverity.ERROR,
                        details={
                            "op": op_call.op,
                            "args": op_call.args,
                            "step": step,
                            "error": str(exc),
                        },
                    )
                )
                break
        return EngineResult(value=current, issues=tuple(issues))
