from __future__ import annotations

from pathlib import Path

import pytest

from connector.infra.cache.db import getCacheDbPath, openCacheDb
from connector.infra.cache.handlers.generic_handler import GenericCacheHandler
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.cache.cache_spec import CacheSpec, FieldSpec
from connector.domain.ports.cache_repository import UpsertResult


def _make_spec() -> CacheSpec:
    return CacheSpec(
        dataset="test",
        table="test_table",
        primary_key=("_id",),
        fields=(
            FieldSpec(name="_id", type="string", nullable=False),
            FieldSpec(name="name", type="string", nullable=False),
            FieldSpec(name="flag", type="bool", nullable=True),
            FieldSpec(name="updated_at", type="datetime", nullable=True),
            FieldSpec(name="alias_field", source="alias", type="string", nullable=True),
        ),
        unique_indexes=(("name",),),
        indexes=(("updated_at",),),
    )


def _setup_db(tmp_path: Path, spec: CacheSpec) -> tuple[SqliteEngine, GenericCacheHandler]:
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    engine = SqliteEngine(conn)
    handler = GenericCacheHandler(spec)
    ensure_cache_ready(engine, [spec])
    return engine, handler


def test_generic_cache_handler_creates_schema(tmp_path: Path):
    spec = _make_spec()
    engine, handler = _setup_db(tmp_path, spec)
    try:
        tables = {row[0] for row in engine.fetchall("SELECT name FROM sqlite_master WHERE type='table'")}
        assert "test_table" in tables
        indexes = {row[1] for row in engine.fetchall("SELECT * FROM sqlite_master WHERE type='index'")}
        assert "uidx_test_table_name" in indexes
        assert "idx_test_table_updated_at" in indexes
    finally:
        engine.conn.close()


def test_generic_cache_handler_upsert_updates(tmp_path: Path):
    spec = _make_spec()
    engine, handler = _setup_db(tmp_path, spec)
    try:
        status1 = handler.upsert(engine, {"_id": "1", "name": "alpha", "flag": True, "alias": "x"})
        status2 = handler.upsert(engine, {"_id": "1", "name": "alpha", "flag": False, "alias": "y"})
        row = engine.fetchone("SELECT flag, alias_field FROM test_table WHERE _id = ?", ("1",))
    finally:
        engine.conn.close()

    assert status1 == UpsertResult.INSERTED
    assert status2 == UpsertResult.UPDATED
    assert row[0] == 0
    assert row[1] == "y"


def test_generic_cache_handler_missing_required_raises(tmp_path: Path):
    spec = _make_spec()
    engine, handler = _setup_db(tmp_path, spec)
    try:
        with pytest.raises(ValueError, match="Missing required cache field"):
            handler.upsert(engine, {"_id": "1"})
    finally:
        engine.conn.close()
