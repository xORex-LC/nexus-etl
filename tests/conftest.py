from __future__ import annotations

import pytest

from connector.domain.diagnostics import build_catalog, configure


@pytest.fixture(autouse=True, scope="session")
def _configure_strict_diagnostics() -> None:
    configure(build_catalog("employees", strict=True))
