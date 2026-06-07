"""Юнит-тесты Polars adapter-а для shared canonicalization plan."""

from __future__ import annotations

import polars as pl
import pytest

from connector.domain.transform_dsl import load_topology_spec_for_dataset
from connector.domain.transform_dsl.compilers.topology import TopologyDsl
from connector.domain.transform_dsl.specs import TopologySpec
from connector.infra.polars import (
    build_canonicalized_scalar_expr,
    build_canonicalized_segments_expr,
    canonicalize_scalar_with_polars,
    canonicalize_segments_with_polars,
)
from tests.runtime_test_support import (
    build_isolated_test_runtime_root,
    tracked_employees_runtime_roots,
)

pytestmark = pytest.mark.unit


def test_polars_canonicalizer_matches_python_for_organizations_topology() -> None:
    build_isolated_test_runtime_root(tracked_employees_runtime_roots()["runtime_root"])
    compiled = TopologyDsl().compile(load_topology_spec_for_dataset("organizations"))

    samples = (
        (" Root ", " Team A "),
        ("Root", "  TEAM   A", ""),
        ("North  Region", "  Finance\tDept  "),
        (),
    )

    for segments in samples:
        assert canonicalize_segments_with_polars(
            segments=segments,
            plan=compiled.polars_expression_plan,
        ) == compiled.python.canonicalize_segments(segments)


def test_polars_canonicalizer_matches_python_for_order_sensitive_ops() -> None:
    spec = TopologySpec.model_validate(
        {
            "dataset": "organizations",
            "topology": {
                "canonicalization": {
                    "ops": [
                        {"op": "compact"},
                        {"op": "trim"},
                        {"op": "lower"},
                        {"op": "regex_replace", "pattern": " +", "repl": "_"},
                    ]
                },
                "source": {
                    "mode": "path_columns",
                    "path_columns": [{"field": "l1"}, {"field": "l2"}, {"field": "l3"}],
                },
                "target": {
                    "mode": "adjacency_list",
                    "node_id_field": "_ouid",
                    "parent_id_field": "parent_id",
                    "target_label_field": "name",
                },
            },
        }
    )
    compiled = TopologyDsl().compile(spec)

    samples = (
        (" Root ", "  ", "\tTeam A\t"),
        ("", " Finance   Dept ", "  "),
        (" North  Region ", " \t ", "Ops"),
        (),
    )

    for segments in samples:
        assert canonicalize_segments_with_polars(
            segments=segments,
            plan=compiled.polars_expression_plan,
        ) == compiled.python.canonicalize_segments(segments)


def test_build_canonicalized_segments_expr_vectorizes_multiple_rows() -> None:
    build_isolated_test_runtime_root(tracked_employees_runtime_roots()["runtime_root"])
    compiled = TopologyDsl().compile(load_topology_spec_for_dataset("organizations"))

    frame = pl.DataFrame(
        {
            "l1": [" Head Office ", " North  Region ", ""],
            "l2": [" Finance   Dept ", "  ", ""],
            "l3": ["", "\tOps\t", ""],
        }
    )

    actual = frame.select(
        build_canonicalized_segments_expr(
            segment_exprs=(pl.col("l1"), pl.col("l2"), pl.col("l3")),
            plan=compiled.polars_expression_plan,
        ).alias("segments")
    ).get_column("segments").to_list()

    expected = [
        list(compiled.python.canonicalize_segments((" Head Office ", " Finance   Dept ", ""))),
        list(compiled.python.canonicalize_segments((" North  Region ", "  ", "\tOps\t"))),
        list(compiled.python.canonicalize_segments(("", "", ""))),
    ]

    assert actual == expected


def test_build_canonicalized_scalar_expr_matches_python_contract() -> None:
    build_isolated_test_runtime_root(tracked_employees_runtime_roots()["runtime_root"])
    compiled = TopologyDsl().compile(load_topology_spec_for_dataset("organizations"))

    frame = pl.DataFrame({"value": ["  HEAD OFFICE  ", "   ", " Finance\tDept "]})

    actual = frame.select(
        build_canonicalized_scalar_expr(
            value_expr=pl.col("value"),
            plan=compiled.polars_expression_plan,
        ).alias("value")
    ).get_column("value").to_list()

    expected = [
        compiled.python.canonicalize_scalar("  HEAD OFFICE  "),
        compiled.python.canonicalize_scalar("   "),
        compiled.python.canonicalize_scalar(" Finance\tDept "),
    ]

    assert actual == expected


def test_canonicalize_scalar_with_polars_matches_python_for_blank_value() -> None:
    build_isolated_test_runtime_root(tracked_employees_runtime_roots()["runtime_root"])
    compiled = TopologyDsl().compile(load_topology_spec_for_dataset("organizations"))

    assert canonicalize_scalar_with_polars(
        value="   ",
        plan=compiled.polars_expression_plan,
    ) == compiled.python.canonicalize_scalar("   ")
