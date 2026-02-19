from __future__ import annotations

import pytest

from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.sqlite.engine import open_sqlite


def test_nested_transactions_are_rejected() -> None:
    engine = open_sqlite(SqliteDbConfig(), ":memory:")
    with engine.transaction():
        with pytest.raises(RuntimeError, match="Nested transactions are not supported"):
            with engine.transaction():
                pass
