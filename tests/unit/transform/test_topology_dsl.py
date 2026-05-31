"""Юнит-тесты topology DSL, canonicalizer-а и loader boundary."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from connector.domain.transform_dsl import load_topology_spec_for_dataset
from connector.domain.transform_dsl.compilers.topology import TopologyDsl
from connector.domain.transform_dsl.specs import TopologySpec
from tests.runtime_test_support import (
    build_isolated_test_runtime_root,
    tracked_employees_runtime_roots,
)

pytestmark = pytest.mark.unit


def test_load_topology_spec_for_dataset_organizations(
    employees_registry_path,
) -> None:
    build_isolated_test_runtime_root(tracked_employees_runtime_roots()["runtime_root"])
    spec = load_topology_spec_for_dataset("organizations")

    assert spec.dataset == "organizations"
    assert [item.field for item in spec.topology.source.path_columns] == [
        "level_1_name",
        "level_2_name",
        "level_3_name",
    ]
    assert spec.topology.target.node_id_field == "_ouid"
    assert spec.topology.target.parent_id_field == "parent_id"
    assert spec.topology.target.target_label_field == "name"
    assert spec.topology.target.payload_target_id_field == "_id"


def test_compiled_topology_canonicalizer_applies_whitelist_ops() -> None:
    spec = TopologySpec.model_validate(
        {
            "dataset": "organizations",
            "topology": {
                "canonicalization": {
                    "ops": [
                        {"op": "trim"},
                        {"op": "lower"},
                        {"op": "regex_replace", "pattern": "\\s+", "repl": " "},
                        {"op": "compact"},
                    ]
                },
                "source": {
                    "mode": "path_columns",
                    "path_columns": [{"field": "l1"}, {"field": "l2"}],
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

    assert compiled.python.canonicalize_segments(("  Root  ", " Team   A ", "   ")) == (
        "root",
        "team a",
    )


def test_topology_canonicalizer_is_symmetric_for_source_and_target_labels() -> None:
    build_isolated_test_runtime_root(tracked_employees_runtime_roots()["runtime_root"])
    compiled = TopologyDsl().compile(load_topology_spec_for_dataset("organizations"))

    source_segments = ("  Head Office ", " Finance   Dept ")
    target_labels = ("Head   Office", "  FINANCE DEPT  ")

    assert compiled.python.canonicalize_segments(
        source_segments
    ) == compiled.python.canonicalize_segments(target_labels)


def test_topology_canonicalizer_dual_form_matches_python_output() -> None:
    build_isolated_test_runtime_root(tracked_employees_runtime_roots()["runtime_root"])
    compiled = TopologyDsl().compile(load_topology_spec_for_dataset("organizations"))

    samples = (
        (" Root ", " Team A "),
        ("Root", "  TEAM   A", ""),
        ("North  Region", "  Finance\tDept  "),
    )

    for segments in samples:
        assert compiled.python.canonicalize_segments(
            segments
        ) == compiled.polars_expression_plan.apply_to_segments(segments)


def test_topology_spec_rejects_non_whitelist_ops_on_pydantic_boundary() -> None:
    with pytest.raises(ValidationError):
        TopologySpec.model_validate(
            {
                "dataset": "organizations",
                "topology": {
                    "canonicalization": {
                        "ops": [
                            {"op": "trim"},
                            {"op": "transliterate"},
                        ]
                    },
                    "source": {
                        "mode": "path_columns",
                        "path_columns": [{"field": "l1"}],
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
