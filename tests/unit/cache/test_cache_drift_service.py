from __future__ import annotations

from connector.domain.cache_core import CacheDriftService


def test_drift_service_detects_schema_version_mismatch() -> None:
    service = CacheDriftService()
    result = service.evaluate_schema_version(expected="6", actual="5")
    assert result.has_drift is True
    assert result.reason == "schema_version_mismatch"


def test_drift_service_returns_no_drift_for_equal_versions() -> None:
    service = CacheDriftService()
    result = service.evaluate_schema_version(expected=6, actual="6")
    assert result.has_drift is False
    assert result.reason is None
