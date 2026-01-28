from __future__ import annotations

from connector.infra.cache.cache_spec import CacheSpec
from connector.infra.cache.handlers.generic_handler import GenericCacheHandler
from connector.infra.cache.sqlite_engine import SqliteEngine

SCHEMA_VERSION = 4


def ensure_base_schema(engine: SqliteEngine) -> int:
    """
    Назначение:
        Создать базовую schema (meta) и применить миграции.
    """
    _create_meta(engine)
    current_version = _get_schema_version(engine) or 0

    if current_version == 0:
        _create_service_tables(engine)
        _set_schema_version(engine, SCHEMA_VERSION)
        return SCHEMA_VERSION

    if current_version < SCHEMA_VERSION:
        if current_version < 2:
            _migrate_to_v2(engine)
        if current_version < 3:
            _migrate_to_v3(engine)
        if current_version < 4:
            _migrate_to_v4(engine)
        _set_schema_version(engine, SCHEMA_VERSION)
        return SCHEMA_VERSION

    return current_version


def ensure_cache_ready(engine: SqliteEngine, cache_specs: list[CacheSpec]) -> int:
    """
    Назначение:
        Инициализирует базовую схему и таблицы датасетов.
    """
    with engine.transaction():
        version = ensure_base_schema(engine)
        for spec in cache_specs:
            GenericCacheHandler(spec).ensure_schema(engine)
    return version


def _create_meta(engine: SqliteEngine) -> None:
    engine.execute(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )


def _get_schema_version(engine: SqliteEngine) -> int | None:
    row = engine.fetchone("SELECT value FROM meta WHERE key='schema_version'")
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _set_schema_version(engine: SqliteEngine, version: int) -> None:
    engine.execute(
        """
        INSERT INTO meta(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        ("schema_version", str(version)),
    )


def _table_exists(engine: SqliteEngine, table: str) -> bool:
    row = engine.fetchone("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return row is not None


def _migrate_to_v2(engine: SqliteEngine) -> None:
    """
    Миграция с v1: пересоздаём таблицу users с обязательными полями match_key/identity.
    Старые данные не копируются, чтобы избежать неконсистентных записей.
    """
    if _table_exists(engine, "users"):
        engine.execute("ALTER TABLE users RENAME TO users_v1_backup")
    # Users schema будет создан через CacheSpec/GenericCacheHandler
    engine.execute("DROP TABLE IF EXISTS users_v1_backup")
    engine.execute(
        """
        INSERT INTO meta(key, value)
        VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        ("users_count", "0"),
    )


def _migrate_to_v3(engine: SqliteEngine) -> None:
    """
    Миграция с v2: добавляем служебные таблицы для identity/pending.
    """
    _create_service_tables(engine)


def _migrate_to_v4(engine: SqliteEngine) -> None:
    """
    Миграция с v3: добавляем payload в pending_links.
    """
    if not _column_exists(engine, "pending_links", "payload"):
        engine.execute("ALTER TABLE pending_links ADD COLUMN payload TEXT")


def _create_service_tables(engine: SqliteEngine) -> None:
    engine.execute(
        """
        CREATE TABLE IF NOT EXISTS identity_index (
            dataset TEXT NOT NULL,
            identity_key TEXT NOT NULL,
            resolved_id TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (dataset, identity_key, resolved_id)
        )
        """
    )
    engine.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_identity_lookup
        ON identity_index(dataset, identity_key)
        """
    )
    engine.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_identity_resolved
        ON identity_index(dataset, resolved_id)
        """
    )
    engine.execute(
        """
        CREATE TABLE IF NOT EXISTS pending_links (
            pending_id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset TEXT NOT NULL,
            source_row_id TEXT NOT NULL,
            field TEXT NOT NULL,
            lookup_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            reason TEXT,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_attempt_at TEXT,
            expires_at TEXT,
            payload TEXT
        )
        """
    )
    engine.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pending_lookup
        ON pending_links(dataset, lookup_key)
        """
    )
    engine.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pending_status
        ON pending_links(status)
        """
    )
    engine.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pending_expires
        ON pending_links(expires_at)
        """
    )


def _column_exists(engine: SqliteEngine, table: str, column: str) -> bool:
    rows = engine.fetchall(f"PRAGMA table_info({table})")
    return any(row[1] == column for row in rows)
