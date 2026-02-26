from __future__ import annotations

from connector.config.models import AppConfig, SqliteConfig
from connector.config.projections import to_vault_db_config
from pathlib import Path

import pytest

from connector.delivery.cli.containers import _vault_db_path
from connector.infra.sqlite.engine import open_sqlite


def test_get_vault_db_path_uses_default_location(tmp_path: Path):
    sqlite = SqliteConfig()
    path = _vault_db_path(str(tmp_path / "cache"), sqlite)
    assert path.endswith("ankey_vault.sqlite3")
    assert str(tmp_path / "cache") in path


def test_get_vault_db_path_uses_config_override(tmp_path: Path):
    custom = str(tmp_path / "custom" / "vault.db")
    sqlite = SqliteConfig(vault_db_path=custom)
    path = _vault_db_path(str(tmp_path / "cache"), sqlite)
    assert path == custom


def test_open_sqlite_applies_vault_pragma_profile(tmp_path: Path):
    """open_sqlite() с to_vault_db_config применяет WAL, busy_timeout и foreign_keys."""
    config = to_vault_db_config(AppConfig(sqlite=SqliteConfig(vault_busy_timeout_ms=7000)))
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
    config = to_vault_db_config(AppConfig())
    engine = open_sqlite(config, db_path)
    try:
        assert (tmp_path / "new-cache").exists()
        assert (tmp_path / "new-cache" / "vault.sqlite3").exists()
    finally:
        engine.close()
