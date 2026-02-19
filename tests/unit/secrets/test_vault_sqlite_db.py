from __future__ import annotations

from pathlib import Path

from connector.config.app_settings import SqliteSettings, build_vault_db_config
from connector.infra.secrets.sqlite.db import (
    DEFAULT_VAULT_DB_PATH_ENV,
    getVaultDbPath,
)
from connector.infra.sqlite.engine import open_sqlite


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


def test_open_sqlite_applies_vault_pragma_profile(tmp_path: Path):
    """open_sqlite() с build_vault_db_config применяет WAL, busy_timeout и foreign_keys."""
    config = build_vault_db_config(SqliteSettings(vault_sqlite_busy_timeout_ms=7000))
    engine = open_sqlite(config, str(tmp_path / "cache" / "ankey_vault.sqlite3"))
    try:
        assert engine.fetchone("PRAGMA journal_mode")[0].upper() == "WAL"
        assert int(engine.fetchone("PRAGMA busy_timeout")[0]) == 7000
        assert int(engine.fetchone("PRAGMA foreign_keys")[0]) == 1
    finally:
        engine.close()


def test_open_sqlite_creates_parent_directory(tmp_path: Path):
    """open_sqlite() создаёт родительскую директорию если она не существует."""
    db_path = str(tmp_path / "new-cache" / "vault.sqlite3")
    config = build_vault_db_config(SqliteSettings())
    engine = open_sqlite(config, db_path)
    try:
        assert (tmp_path / "new-cache").exists()
        assert (tmp_path / "new-cache" / "vault.sqlite3").exists()
    finally:
        engine.close()
