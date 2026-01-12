from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1

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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            _id TEXT PRIMARY KEY,
            _ouid INTEGER UNIQUE,
            personnel_number TEXT,
            last_name TEXT,
            first_name TEXT,
            middle_name TEXT,
            match_key TEXT,
            mail TEXT,
            user_name TEXT,
            phone TEXT,
            updated_at TEXT
        )
        """
    )
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

    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_match_key ON users(match_key)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_personnel_number ON users(personnel_number)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_users_ouid ON users(_ouid)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_org_parent ON organizations(parent_id)")

    conn.execute(
        """
        INSERT INTO meta(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        ("schema_version", str(SCHEMA_VERSION)),
    )

    conn.commit()
    return SCHEMA_VERSION

def runMigrations(conn: sqlite3.Connection) -> None:
    """
    Зарезервировано для будущих миграций схемы.
    """
    # Пока нет миграций, схема выставляется ensureSchema.
    return