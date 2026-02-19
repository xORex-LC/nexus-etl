"""
Unit-тесты для SqliteSettings и build_*_db_config из connector/config/app_settings.py.

Проверяют: чтение env vars, env_ignore_empty, override chain.
"""
from __future__ import annotations

import pytest

from connector.config.app_settings import (
    SqliteSettings,
    build_cache_db_config,
    build_identity_db_config,
    build_vault_db_config,
)


def test_sqlite_settings_reads_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """ANKEY_SQLITE_BUSY_TIMEOUT_MS из env подхватывается как глобальный дефолт."""
    monkeypatch.setenv("ANKEY_SQLITE_BUSY_TIMEOUT_MS", "9999")
    s = SqliteSettings()
    assert s.sqlite_busy_timeout_ms == 9999


def test_sqlite_settings_env_ignore_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустая строка в env vars не перетирает дефолт (env_ignore_empty=True)."""
    monkeypatch.setenv("ANKEY_SQLITE_BUSY_TIMEOUT_MS", "")
    s = SqliteSettings()
    assert s.sqlite_busy_timeout_ms == 5000  # дефолт сохранён


def test_build_vault_db_config_uses_global_defaults_when_overrides_are_none() -> None:
    """vault_sqlite_busy_timeout_ms=None → берётся sqlite_busy_timeout_ms (global)."""
    s = SqliteSettings(
        sqlite_busy_timeout_ms=8000,
        vault_sqlite_busy_timeout_ms=None,
        vault_sqlite_journal_mode=None,
        sqlite_journal_mode="WAL",
    )
    config = build_vault_db_config(s)
    assert config.busy_timeout_ms == 8000
    assert config.journal_mode == "WAL"


def test_build_vault_db_config_uses_override_when_set() -> None:
    """vault_sqlite_busy_timeout_ms=1234 → именно 1234 попадает в config."""
    s = SqliteSettings(
        sqlite_busy_timeout_ms=5000,
        vault_sqlite_busy_timeout_ms=1234,
        vault_sqlite_journal_mode="DELETE",
        sqlite_journal_mode="WAL",
    )
    config = build_vault_db_config(s)
    assert config.busy_timeout_ms == 1234
    assert config.journal_mode == "DELETE"
    assert config.transaction_mode == "immediate"
    assert config.schema_retry_count == s.vault_sqlite_schema_retry_count


def test_build_cache_db_config_uses_deferred_mode() -> None:
    """Cache DB всегда использует transaction_mode=deferred."""
    s = SqliteSettings()
    config = build_cache_db_config(s)
    assert config.transaction_mode == "deferred"


def test_build_identity_db_config_uses_global_defaults() -> None:
    """Identity DB строится только из глобальных дефолтов (нет per-DB overrides)."""
    s = SqliteSettings(
        sqlite_busy_timeout_ms=6000,
        sqlite_journal_mode="DELETE",
        sqlite_synchronous="FULL",
        sqlite_wal_autocheckpoint=2000,
    )
    config = build_identity_db_config(s)
    assert config.transaction_mode == "deferred"
    assert config.busy_timeout_ms == 6000
    assert config.journal_mode == "DELETE"
    assert config.synchronous == "FULL"
    assert config.wal_autocheckpoint == 2000
    assert config.schema_retry_count == 0  # нет retry для identity
