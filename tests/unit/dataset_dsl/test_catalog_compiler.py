"""Tests for catalog_compiler."""

from __future__ import annotations

import pytest

from connector.domain.dataset_dsl.catalog_compiler import compile_diagnostic_catalog
from connector.domain.dataset_dsl.specs import DiagnosticEntrySpec
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.models import DiagnosticSeverity


class TestCompileDiagnosticCatalog:
    def test_basic(self):
        entries = [
            DiagnosticEntrySpec(
                code="BAD_EMAIL",
                system_code="DATA_INVALID",
                severity="error",
                message="invalid email",
            ),
        ]
        catalog = compile_diagnostic_catalog(entries, strict=False)
        assert catalog.contains("BAD_EMAIL")
        assert catalog.classify("BAD_EMAIL") == SystemErrorCode.DATA_INVALID

    def test_multiple_entries(self):
        entries = [
            DiagnosticEntrySpec(code="E1", system_code="DATA_INVALID", severity="error"),
            DiagnosticEntrySpec(code="E2", system_code="DATA_INVALID", severity="warning"),
        ]
        catalog = compile_diagnostic_catalog(entries, strict=False)
        assert catalog.contains("E1")
        assert catalog.contains("E2")

    def test_empty_entries(self):
        catalog = compile_diagnostic_catalog([], strict=False)
        assert not catalog.contains("anything")

    def test_strict_mode(self):
        catalog = compile_diagnostic_catalog([], strict=True)
        with pytest.raises(Exception):
            catalog.classify("UNKNOWN")

    def test_invalid_system_code_raises(self):
        entries = [
            DiagnosticEntrySpec(code="E1", system_code="NONEXISTENT", severity="error"),
        ]
        with pytest.raises(ValueError, match="Unknown system_code"):
            compile_diagnostic_catalog(entries, strict=False)

    def test_invalid_severity_raises(self):
        entries = [
            DiagnosticEntrySpec(code="E1", system_code="DATA_INVALID", severity="critical"),
        ]
        with pytest.raises(ValueError, match="Unknown severity"):
            compile_diagnostic_catalog(entries, strict=False)

