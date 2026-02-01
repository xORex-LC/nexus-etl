from __future__ import annotations

import pytest

from connector.domain.diagnostics import DiagnosticFactory, build_core_catalog, configure


@pytest.fixture(autouse=True, scope="session")
def _configure_strict_diagnostics() -> None:
    configure(DiagnosticFactory(build_core_catalog(strict=True)))
