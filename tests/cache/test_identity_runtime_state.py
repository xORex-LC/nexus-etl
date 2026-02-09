from __future__ import annotations

import sqlite3
from pathlib import Path

from connector.datasets.cache_registry import list_cache_specs
from connector.infra.cache.db import getCacheDbPath, openCacheDb
from connector.infra.cache.factory import build_sqlite_cache_gateway
from connector.infra.cache.gateway import SqliteCacheGateway
from connector.infra.cache.sqlite_engine import SqliteEngine


def _build_repo(tmp_path: Path) -> tuple[SqliteCacheGateway, sqlite3.Connection]:
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    engine = SqliteEngine(conn)
    return build_sqlite_cache_gateway(engine=engine, cache_specs=list_cache_specs()), conn


def test_runtime_state_set_get_and_clear_scope(tmp_path: Path):
    repo, conn = _build_repo(tmp_path)
    try:
        repo.set_runtime_state("run:1", "employees", "dedup:k1", "fp1")
        repo.set_runtime_state("run:2", "employees", "dedup:k1", "fp2")

        assert repo.get_runtime_state("run:1", "employees", "dedup:k1") == "fp1"
        assert repo.get_runtime_state("run:2", "employees", "dedup:k1") == "fp2"

        repo.set_runtime_state("run:1", "employees", "dedup:k1", "fp1-new")
        assert repo.get_runtime_state("run:1", "employees", "dedup:k1") == "fp1-new"

        repo.clear_runtime_scope("run:1")
        assert repo.get_runtime_state("run:1", "employees", "dedup:k1") is None
        assert repo.get_runtime_state("run:2", "employees", "dedup:k1") == "fp2"
    finally:
        conn.close()
