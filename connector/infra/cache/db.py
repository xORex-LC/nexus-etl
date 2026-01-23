from __future__ import annotations

import sqlite3
from pathlib import Path

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
