from __future__ import annotations

import sqlite3

import pytest

from connector.infra.cache.backends.sqlite.engine import SqliteEngine


def test_nested_transactions_are_rejected() -> None:
    conn = sqlite3.connect(":memory:")
    try:
        engine = SqliteEngine(conn)
        with engine.transaction():
            with pytest.raises(RuntimeError, match="Nested cache transactions"):
                with engine.transaction():
                    pass
    finally:
        conn.close()
