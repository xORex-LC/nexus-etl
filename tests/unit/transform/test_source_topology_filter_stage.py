"""Юнит-тесты row-level фильтра source topology validation."""

from __future__ import annotations

import pytest

from connector.domain.dependency_tree import SourceAnchoringVerdict
from connector.domain.diagnostics import build_core_catalog
from connector.domain.models import DiagnosticStage, RowRef
from connector.domain.ports.topology import SourceTopologyValidationState
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform.stages.source_topology_filter import (
    SourceTopologyFilterStage,
)

pytestmark = pytest.mark.unit


def test_source_topology_filter_stage_drops_unanchored_row_with_row_ref() -> None:
    state = SourceTopologyValidationState(
        node_id_field="code",
        dropped={
            "382": SourceAnchoringVerdict(
                node_id="382",
                reason="missing_parent",
                broken_at_parent_id="378",
            )
        },
        on_unanchored="skip",
    )
    result = TransformResult(
        record=SourceRecord(line_no=2, record_id="line:2", values={}),
        row={"code": "382", "name": "Service"},
        row_ref=RowRef(
            line_no=2,
            row_id="line:2",
            identity_primary="code",
            identity_value="382",
        ),
        match_key=None,
    )

    stage = SourceTopologyFilterStage(
        validation=state,
        catalog=build_core_catalog(strict=True),
    )

    filtered = list(stage.run((result,)))

    assert filtered[0].row is None
    assert filtered[0].errors[0].code == "TOPOLOGY_SOURCE_UNANCHORED"
    assert filtered[0].errors[0].stage == DiagnosticStage.TOPOLOGY_VALIDATE
    assert filtered[0].errors[0].record_ref == result.row_ref


def test_source_topology_filter_stage_warn_policy_keeps_row() -> None:
    state = SourceTopologyValidationState(
        node_id_field="code",
        dropped={
            "382": SourceAnchoringVerdict(
                node_id="382",
                reason="missing_parent",
                broken_at_parent_id="378",
            )
        },
        on_unanchored="warn",
    )
    result = TransformResult(
        record=SourceRecord(line_no=2, record_id="line:2", values={}),
        row={"code": "382"},
        row_ref=None,
        match_key=None,
    )

    stage = SourceTopologyFilterStage(
        validation=state,
        catalog=build_core_catalog(strict=True),
    )

    filtered = list(stage.run((result,)))

    assert filtered[0].row == {"code": "382"}
    assert filtered[0].warnings[0].code == "TOPOLOGY_SOURCE_UNANCHORED"
    assert filtered[0].warnings[0].stage == DiagnosticStage.TOPOLOGY_VALIDATE
