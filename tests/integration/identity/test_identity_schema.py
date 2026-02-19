"""
Integration tests for connector/infra/identity/sqlite/schema.py.
Verifies that ensure_identity_schema() creates the correct tables and that
identity and cache schemas are properly separated.
"""
from __future__ import annotations

from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.identity.sqlite.schema import ensure_identity_schema
from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.sqlite.engine import open_sqlite


def test_identity_schema_creates_tables():
    """ensure_identity_schema() создаёт все три identity-таблицы."""
    engine = open_sqlite(SqliteDbConfig(), ":memory:")
    ensure_identity_schema(engine)

    table_rows = engine.fetchall(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )
    table_names = {row[0] for row in table_rows}

    assert "identity_index" in table_names
    assert "pending_links" in table_names
    assert "identity_runtime_state" in table_names


def test_identity_schema_is_separate_from_cache_schema():
    """
    cache.sqlite3 (после ensure_cache_ready) не содержит identity-таблицы;
    identity.sqlite3 (после ensure_identity_schema) не содержит dataset-таблицы.
    """
    cache_engine = open_sqlite(SqliteDbConfig(), ":memory:")
    ensure_cache_ready(cache_engine, [])

    cache_tables = {
        row[0]
        for row in cache_engine.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    }
    # Identity tables must NOT be in cache.sqlite3 on fresh init
    assert "identity_index" not in cache_tables
    assert "pending_links" not in cache_tables
    assert "identity_runtime_state" not in cache_tables

    identity_engine = open_sqlite(SqliteDbConfig(), ":memory:")
    ensure_identity_schema(identity_engine)

    identity_tables = {
        row[0]
        for row in identity_engine.fetchall("SELECT name FROM sqlite_master WHERE type='table'")
    }
    # Dataset tables must NOT be in identity.sqlite3
    assert "users" not in identity_tables
    assert "meta" not in identity_tables
