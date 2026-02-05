"""
Назначение:
    Универсальный движок трансформаций: применяет операции DSL к значениям.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from connector.domain.transform.dsl.issues import DslIssue, DslSeverity
from connector.domain.transform.dsl.registry import OperationRegistry
from connector.domain.transform.dsl.specs import OperationCall


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
        for op_call in ops:
            op = self.registry.get(op_call.op)
            if op is None:
                issues.append(
                    DslIssue(
                        code="DSL_OP_UNKNOWN",
                        message=f"Unknown operation '{op_call.op}'",
                        severity=DslSeverity.ERROR,
                    )
                )
                break
            try:
                current = op.func(current, **op_call.args)
            except Exception as exc:  # noqa: BLE001
                issues.append(
                    DslIssue(
                        code="DSL_OP_FAILED",
                        message=str(exc),
                        severity=DslSeverity.ERROR,
                    )
                )
                break
        return EngineResult(value=current, issues=tuple(issues))
