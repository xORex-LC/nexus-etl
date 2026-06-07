"""
Назначение:
    Общие утилиты для стадий transform (не зависят от DSL).
"""

from connector.domain.transform.common.canonicalization import (
    CompiledCanonicalizeOp,
    CompiledCanonicalizer,
    CompiledPolarsExpressionPlan,
    apply_compiled_canonicalizer_ops,
)
from connector.domain.transform.common.text import (
    normalize_for_compare,
    normalize_text,
)

__all__ = [
    "CompiledCanonicalizeOp",
    "CompiledCanonicalizer",
    "CompiledPolarsExpressionPlan",
    "apply_compiled_canonicalizer_ops",
    "normalize_for_compare",
    "normalize_text",
]
