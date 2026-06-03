"""Polars infra adapters — vectorized исполнение shared runtime-планов.

Пакет содержит infra-level адаптеры, которые интерпретируют transport-neutral
domain contracts через Polars expressions. Здесь разрешено зависеть от
`polars`, но семантика canonicalization по-прежнему определяется domain-
слоем.
"""

from .canonicalization import (
    build_canonicalized_scalar_expr,
    build_canonicalized_segments_expr,
    canonicalize_scalar_with_polars,
    canonicalize_segments_with_polars,
)

__all__ = [
    "build_canonicalized_scalar_expr",
    "build_canonicalized_segments_expr",
    "canonicalize_scalar_with_polars",
    "canonicalize_segments_with_polars",
]
