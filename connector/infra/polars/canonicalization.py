"""Polars canonicalization adapter — vectorized runtime поверх shared plan.

Этот модуль исполняет `CompiledPolarsExpressionPlan` через Polars expressions,
не меняя domain compile contract. Он нужен как infra-level accelerator для
массовой canonicalization сегментов и scalar lookup-значений.

Responsibilities:
    - Переводить shared compiled canonicalization plan в Polars expressions
    - Давать vectorized helpers для list-of-segments и scalar values
    - Сохранять семантическую parity с Python canonicalizer-ом

Out of scope:
    - Компиляция YAML/spec в canonicalization plan
    - Topology/cache-specific orchestration
    - Изменение payload/source/target значений вне comparison path
"""

from __future__ import annotations

from typing import Sequence

import polars as pl

from connector.domain.transform.common import (
    CompiledCanonicalizeOp,
    CompiledPolarsExpressionPlan,
)


def build_canonicalized_segments_expr(
    *,
    segment_exprs: Sequence[pl.Expr],
    plan: CompiledPolarsExpressionPlan,
) -> pl.Expr:
    """Собрать Polars expression для канонизации ordered textual segments.

    Args:
        segment_exprs: Expressions, каждая из которых даёт один сегмент пути.
        plan: Shared compiled canonicalization plan.

    Returns:
        `pl.Expr`, вычисляющий `list[str]` с канонизированными сегментами.
    """

    if segment_exprs:
        current = pl.concat_list([expr.cast(pl.String) for expr in segment_exprs])
    else:
        current = pl.lit([], dtype=pl.List(pl.String))
    for step in plan.ops:
        if step.scope == "segment":
            current = current.list.eval(_build_segment_expr(pl.element(), step))
            continue
        if step.scope == "segments":
            current = _build_segments_expr(current, step)
            continue
        raise ValueError(f"Unsupported canonicalization scope: {step.scope}")
    return current


def build_canonicalized_scalar_expr(
    *,
    value_expr: pl.Expr,
    plan: CompiledPolarsExpressionPlan,
) -> pl.Expr:
    """Собрать Polars expression для канонизации одного scalar значения.

    Контракт повторяет Python canonicalizer: если после pipeline сегменты
    полностью исчезли, результатом считается пустая строка, а не `null`.
    """

    segments_expr = build_canonicalized_segments_expr(
        segment_exprs=(value_expr,),
        plan=plan,
    )
    return pl.coalesce(
        [
            segments_expr.list.get(0, null_on_oob=True),
            pl.lit(""),
        ]
    )


def canonicalize_segments_with_polars(
    *,
    segments: tuple[str, ...],
    plan: CompiledPolarsExpressionPlan,
) -> tuple[str, ...]:
    """Материализовать vectorized canonicalization для одного набора сегментов.

    Хелпер нужен для unit-тестов parity и для локального adapter-level
    использования там, где удобнее подать raw tuple, а не строить DataFrame
    вручную.
    """

    frame = pl.DataFrame(
        {"_row": [0]}
    )
    expr = build_canonicalized_segments_expr(
        segment_exprs=tuple(
            pl.lit(value, dtype=pl.String) for value in segments
        ),
        plan=plan,
    ).alias("canonical_segments")
    result = frame.select(expr).to_series(0).item()
    if result is None:
        return ()
    return tuple(str(value) for value in result)


def canonicalize_scalar_with_polars(
    *,
    value: str,
    plan: CompiledPolarsExpressionPlan,
) -> str:
    """Материализовать vectorized canonicalization для одного scalar значения."""

    frame = pl.DataFrame({"value": [value]})
    result = frame.select(
        build_canonicalized_scalar_expr(
            value_expr=pl.col("value"),
            plan=plan,
        ).alias("canonical_value")
    ).item()
    return "" if result is None else str(result)


def _build_segment_expr(expr: pl.Expr, step: CompiledCanonicalizeOp) -> pl.Expr:
    """Построить Polars expression для segment-scoped canonicalization шага."""

    args = step.args_dict()
    if step.op == "trim":
        return expr.str.strip_chars()
    if step.op == "lower":
        return expr.str.to_lowercase()
    if step.op == "regex_replace":
        return expr.str.replace_all(args["pattern"], args["repl"])
    raise ValueError(f"Unsupported canonicalization op for Polars adapter: {step.op}")


def _build_segments_expr(expr: pl.Expr, step: CompiledCanonicalizeOp) -> pl.Expr:
    """Построить Polars expression для segments-scoped canonicalization шага."""

    if step.op != "compact":
        raise ValueError(f"Unsupported canonicalization op for Polars adapter: {step.op}")

    return (
        expr.list.eval(
            pl.when(
                pl.element().is_null() | (pl.element().str.strip_chars() == "")
            )
            .then(None)
            .otherwise(pl.element())
        )
        .list.drop_nulls()
    )
