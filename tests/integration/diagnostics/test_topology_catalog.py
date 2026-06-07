from __future__ import annotations

import pytest

from connector.domain.diagnostics import build_catalog, build_error
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.models import DiagnosticSeverity, DiagnosticStage

pytestmark = pytest.mark.integration


def test_topology_catalog_entries_are_available_via_runtime_catalog() -> None:
    catalog = build_catalog(None, strict=True)

    item = build_error(
        catalog=catalog,
        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
        code="TOPOLOGY_PARENT_MISSING",
        details={"node_id": "child", "parent_id": "missing"},
    )

    assert item.stage == DiagnosticStage.TOPOLOGY_BOOTSTRAP
    assert item.severity == DiagnosticSeverity.ERROR
    assert item.details == {"node_id": "child", "parent_id": "missing"}
    assert catalog.classify(item.code) == SystemErrorCode.DATA_INVALID
