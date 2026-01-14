from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

def getCacheDbPath(cacheDir: str) -> str:
    """
    Возвращает путь к файлу кэша в указанном каталоге.
    """
    return str(Path(cacheDir) / "ankey_cache.sqlite3")

def openCacheDb(dbPath: str) -> sqlite3.Connection:
    """
    Открывает/создаёт SQLite БД с нужными PRAGMA/timeout.
    """
    Path(dbPath).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(dbPath, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn

def ensureSchema(conn: sqlite3.Connection) -> int:
    """
    Создаёт таблицы/индексы при первом запуске и записывает schema_version.
    """
    _create_meta(conn)
    current_version = _get_schema_version(conn)
    if current_version is None:
        current_version = 0

    if current_version == 0:
        _create_base_schema(conn)
        runMigrations(conn, current_version)
        _set_schema_version(conn, SCHEMA_VERSION)
        conn.commit()
        return SCHEMA_VERSION

    if current_version < SCHEMA_VERSION:
        runMigrations(conn, current_version)
        _set_schema_version(conn, SCHEMA_VERSION)
        conn.commit()
        return SCHEMA_VERSION

    return current_version

def runMigrations(conn: sqlite3.Connection, current_version: int) -> None:
    """
    Выполняет миграции схемы между версиями.
    """
    if current_version < 2:
        _migrate_to_v2(conn)

# Internal helpers
def _create_meta(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )

def _get_schema_version(conn: sqlite3.Connection) -> int | None:
    row = conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None

def _set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        """
        INSERT INTO meta(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        ("schema_version", str(version)),
    )

def _create_base_schema(conn: sqlite3.Connection) -> None:
    """
    Создаёт таблицы для новой схемы (v2) с ограничениями NOT NULL.
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS organizations (
            _ouid INTEGER PRIMARY KEY,
            code TEXT,
            name TEXT,
            parent_id INTEGER,
            updated_at TEXT
        )
        """
    )
    _create_users_table_v2(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_org_parent ON organizations(parent_id)")

def _create_users_table_v2(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            _id TEXT PRIMARY KEY,
            _ouid INTEGER NOT NULL UNIQUE,
            personnel_number TEXT NOT NULL,
            last_name TEXT NOT NULL,
            first_name TEXT NOT NULL,
            middle_name TEXT NOT NULL,
            match_key TEXT NOT NULL,
            mail TEXT NOT NULL,
            user_name TEXT NOT NULL,
            phone TEXT,
            usr_org_tab_num TEXT NOT NULL,
            organization_id INTEGER NOT NULL,
            account_status TEXT,
            deletion_date TEXT,
            _rev TEXT,
            manager_ouid INTEGER,
            is_logon_disabled INTEGER,
            position TEXT,
            updated_at TEXT
        )
        """
    )
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_match_key ON users(match_key)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_ouid ON users(_ouid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_personnel_number ON users(personnel_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_usr_org_tab_num ON users(usr_org_tab_num)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_org_id ON users(organization_id)")

def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None

def _migrate_to_v2(conn: sqlite3.Connection) -> None:
    """
    Миграция с v1: пересоздаём таблицу users с обязательными полями match_key/identity.
    Старые данные не копируются, чтобы избежать неконсистентных записей.
    """
    if _table_exists(conn, "users"):
        conn.execute("ALTER TABLE users RENAME TO users_v1_backup")
    _create_users_table_v2(conn)
    conn.execute("DROP TABLE IF EXISTS users_v1_backup")
    # Сбросим счётчик пользователей, так как таблица пересоздана
    conn.execute(
        """
        INSERT INTO meta(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        ("users_count", "0"),
    )