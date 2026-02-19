from __future__ import annotations

from pathlib import Path

from connector.infra.secrets.sqlite.db import (
    DEFAULT_VAULT_DB_PATH_ENV,
    VaultSqliteDb,
    getVaultDbPath,
    openVaultDb,
)


def test_get_vault_db_path_uses_default_location(tmp_path: Path):
    path = getVaultDbPath(cacheDir=tmp_path / "cache", env={})
    assert path.endswith("ankey_vault.sqlite3")
    assert str(tmp_path / "cache") in path


def test_get_vault_db_path_uses_env_override(tmp_path: Path):
    custom = tmp_path / "custom" / "vault.db"
    path = getVaultDbPath(
        cacheDir=tmp_path / "cache",
        env={DEFAULT_VAULT_DB_PATH_ENV: str(custom)},
    )
    assert path == str(custom)


def test_open_vault_db_applies_sqlite_profile(tmp_path: Path):
    db_path = tmp_path / "cache" / "ankey_vault.sqlite3"
    conn = openVaultDb(db_path, busy_timeout_ms=7000, env={})
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0].upper() == "WAL"
        assert int(conn.execute("PRAGMA busy_timeout").fetchone()[0]) == 7000
        assert int(conn.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        assert conn.execute("PRAGMA synchronous").fetchone()[0] in {1, 2}
    finally:
        conn.close()


def test_vault_sqlite_db_creates_parent_directory(tmp_path: Path):
    db_path = tmp_path / "new-cache" / "vault.sqlite3"
    db = VaultSqliteDb(db_path=str(db_path))
    try:
        assert db_path.parent.exists()
        assert db_path.exists()
    finally:
        db.close()
