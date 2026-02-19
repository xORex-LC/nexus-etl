"""
Назначение:
    SQLite path/open policy для отдельного vault DB-файла.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Mapping
from pathlib import Path

DEFAULT_VAULT_DB_FILENAME = "ankey_vault.sqlite3"
DEFAULT_VAULT_DB_PATH_ENV = "ANKEY_VAULT_DB_PATH"
DEFAULT_VAULT_BUSY_TIMEOUT_ENV = "ANKEY_VAULT_SQLITE_BUSY_TIMEOUT_MS"
DEFAULT_VAULT_JOURNAL_MODE_ENV = "ANKEY_VAULT_SQLITE_JOURNAL_MODE"

DEFAULT_BUSY_TIMEOUT_MS = 5000
MIN_BUSY_TIMEOUT_MS = 5000
MAX_BUSY_TIMEOUT_MS = 10000

_ALLOWED_JOURNAL_MODES = {"WAL", "DELETE", "MEMORY", "TRUNCATE", "PERSIST", "OFF"}


def getVaultDbPath(
    cacheDir: str | Path = "cache",
    *,
    env_var: str = DEFAULT_VAULT_DB_PATH_ENV,
    env: Mapping[str, str] | None = None,
) -> str:
    """
    Назначение:
        Вернуть путь к vault DB:
        - из `ANKEY_VAULT_DB_PATH`, если задан;
        - иначе `cache/ankey_vault.sqlite3`.
    """
    source = env if env is not None else os.environ
    raw_path = source.get(env_var)
    if raw_path and raw_path.strip():
        return str(Path(raw_path.strip()))
    return str(Path(cacheDir) / DEFAULT_VAULT_DB_FILENAME)


def openVaultDb(
    dbPath: str | Path,
    *,
    busy_timeout_ms: int | None = None,
    env: Mapping[str, str] | None = None,
) -> sqlite3.Connection:
    """
    Назначение:
        Открыть/создать SQLite vault DB c профилем WAL и bounded busy_timeout.

    Инварианты:
        - isolation_level=None для явного управления транзакциями (`BEGIN IMMEDIATE`);
        - row_factory=sqlite3.Row для предсказуемого маппинга записей.
    """
    path = Path(dbPath)
    path.parent.mkdir(parents=True, exist_ok=True)

    resolved_timeout = _resolve_busy_timeout_ms(value=busy_timeout_ms, env=env)
    timeout_seconds = max(1, resolved_timeout) / 1000.0

    conn = sqlite3.connect(str(path), timeout=timeout_seconds, isolation_level=None)
    conn.row_factory = sqlite3.Row

    journal_mode = _resolve_journal_mode(env=env)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute(f"PRAGMA journal_mode = {journal_mode}")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute(f"PRAGMA busy_timeout = {resolved_timeout}")
    return conn


class VaultSqliteDb:
    """
    Назначение:
        Runtime-обёртка над vault SQLite connection/path policy.
    """

    def __init__(
        self,
        *,
        db_path: str | None = None,
        cache_dir: str | Path = "cache",
        env: Mapping[str, str] | None = None,
        busy_timeout_ms: int | None = None,
    ) -> None:
        self.db_path = Path(db_path) if db_path is not None else Path(getVaultDbPath(cache_dir, env=env))
        self.busy_timeout_ms = _resolve_busy_timeout_ms(value=busy_timeout_ms, env=env)
        self.conn = openVaultDb(self.db_path, busy_timeout_ms=self.busy_timeout_ms, env=env)

    def close(self) -> None:
        """Освободить SQLite connection."""
        self.conn.close()


def _resolve_busy_timeout_ms(*, value: int | None, env: Mapping[str, str] | None) -> int:
    if value is not None:
        return _clamp_busy_timeout(value)
    source = env if env is not None else os.environ
    raw_timeout = source.get(DEFAULT_VAULT_BUSY_TIMEOUT_ENV)
    if raw_timeout is None or not raw_timeout.strip():
        return DEFAULT_BUSY_TIMEOUT_MS
    try:
        parsed = int(raw_timeout.strip())
    except ValueError:
        return DEFAULT_BUSY_TIMEOUT_MS
    return _clamp_busy_timeout(parsed)


def _clamp_busy_timeout(value: int) -> int:
    if value < MIN_BUSY_TIMEOUT_MS:
        return MIN_BUSY_TIMEOUT_MS
    if value > MAX_BUSY_TIMEOUT_MS:
        return MAX_BUSY_TIMEOUT_MS
    return value


def _resolve_journal_mode(*, env: Mapping[str, str] | None) -> str:
    source = env if env is not None else os.environ
    raw_mode = (source.get(DEFAULT_VAULT_JOURNAL_MODE_ENV) or "WAL").strip().upper()
    if raw_mode not in _ALLOWED_JOURNAL_MODES:
        return "WAL"
    return raw_mode
