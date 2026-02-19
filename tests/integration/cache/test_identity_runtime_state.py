from __future__ import annotations

from pathlib import Path

from connector.infra.identity.sqlite.identity_repository import SqliteIdentityRepository
from connector.infra.identity.sqlite.schema import ensure_identity_schema
from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.sqlite.engine import open_sqlite, SqliteEngine


def _build_repo(tmp_path: Path) -> tuple[SqliteIdentityRepository, SqliteEngine]:
    engine = open_sqlite(SqliteDbConfig(), str(tmp_path / "cache" / "identity.sqlite3"))
    ensure_identity_schema(engine)
    return SqliteIdentityRepository(engine), engine


def test_runtime_state_set_get_and_clear_scope(tmp_path: Path):
    repo, engine = _build_repo(tmp_path)
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
        engine.close()
