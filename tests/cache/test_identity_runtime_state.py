from __future__ import annotations

import sqlite3
from pathlib import Path

from connector.datasets.cache_registry import list_cache_specs
from connector.infra.cache.db import getCacheDbPath, openCacheDb
from connector.infra.cache.identity_repository import SqliteIdentityRepository
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine


def _build_repo(tmp_path: Path) -> tuple[SqliteIdentityRepository, sqlite3.Connection]:
    cache_dir = tmp_path / "cache"
    db_path = Path(getCacheDbPath(cache_dir))
    conn = openCacheDb(str(db_path))
    engine = SqliteEngine(conn)
    ensure_cache_ready(engine, list_cache_specs())
    return SqliteIdentityRepository(engine), conn


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

