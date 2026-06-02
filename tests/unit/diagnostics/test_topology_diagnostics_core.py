from __future__ import annotations

import pytest

from connector.domain.diagnostics import build_core_catalog, build_error, build_warning
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.models import DiagnosticSeverity, DiagnosticStage

pytestmark = pytest.mark.unit


def test_topology_bootstrap_stage_exists() -> None:
    assert DiagnosticStage.TOPOLOGY_BOOTSTRAP.value == "TOPOLOGY_BOOTSTRAP"


def test_topology_codes_are_classified_in_core_catalog() -> None:
    catalog = build_core_catalog(strict=True)

    assert (
        catalog.classify("TOPOLOGY_SOURCE_PATH_EMPTY") == SystemErrorCode.DATA_INVALID
    )
    assert catalog.classify("TOPOLOGY_DUPLICATE_NODE") == SystemErrorCode.DATA_INVALID
    assert catalog.classify("TOPOLOGY_PARENT_MISSING") == SystemErrorCode.DATA_INVALID
    assert catalog.classify("TOPOLOGY_CYCLE_DETECTED") == SystemErrorCode.DATA_INVALID
    assert catalog.classify("TOPOLOGY_TARGET_EMPTY") == SystemErrorCode.CACHE_ERROR
    assert catalog.classify("TOPOLOGY_TARGET_STALE") == SystemErrorCode.CACHE_ERROR
    assert (
        catalog.classify("TOPOLOGY_TARGET_CACHE_SPEC_MISSING")
        == SystemErrorCode.CACHE_ERROR
    )
    assert (
        catalog.classify("TOPOLOGY_SNAPSHOT_NOT_AVAILABLE")
        == SystemErrorCode.INTERNAL_ERROR
    )
    assert (
        catalog.classify("TOPOLOGY_SOURCE_UNANCHORED")
        == SystemErrorCode.DATA_INVALID
    )


def test_topology_warning_codes_keep_warning_severity() -> None:
    catalog = build_core_catalog(strict=True)

    malformed = build_warning(
        catalog=catalog,
        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
        code="TOPOLOGY_SOURCE_PATH_MALFORMED",
    )
    collision = build_warning(
        catalog=catalog,
        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
        code="TOPOLOGY_SOURCE_COLLISION",
    )

    assert malformed.severity == DiagnosticSeverity.WARNING
    assert collision.severity == DiagnosticSeverity.WARNING


def test_topology_error_codes_keep_error_severity() -> None:
    catalog = build_core_catalog(strict=True)

    item = build_error(
        catalog=catalog,
        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
        code="TOPOLOGY_SOURCE_PATH_EMPTY",
    )

    assert item.severity == DiagnosticSeverity.ERROR
