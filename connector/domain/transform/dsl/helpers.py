"""
Назначение:
    Общие helper-функции для DSL стадий.
"""

from __future__ import annotations

from typing import Any, Iterable

from connector.domain.transform.dsl.engine import TransformationEngine
from connector.domain.transform.dsl.issues import DslIssue
from connector.domain.transform.dsl.specs import OperationCall


def apply_ops(
    engine: TransformationEngine,
    value: Any,
    ops: Iterable[OperationCall],
) -> tuple[Any, list[DslIssue]]:
    """
    Назначение:
        Применить операции DSL и вернуть значение + список проблем.
    """
    result = engine.apply(value, ops)
    return result.value, list(result.issues)
