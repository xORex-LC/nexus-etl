from __future__ import annotations

from connector.infra.cache.handlers.registry import CacheHandlerRegistry
from connector.infra.cache.sqlite_engine import SqliteEngine

SCHEMA_VERSION = 2


def ensure_base_schema(engine: SqliteEngine) -> int:
    """
    Назначение:
        Создать базовую schema (meta) и применить миграции.
    """
    _create_meta(engine)
    current_version = _get_schema_version(engine) or 0

    if current_version == 0:
        _set_schema_version(engine, SCHEMA_VERSION)
        return SCHEMA_VERSION

    if current_version < SCHEMA_VERSION:
        if current_version < 2:
            _migrate_to_v2(engine)
        _set_schema_version(engine, SCHEMA_VERSION)
        return SCHEMA_VERSION

    return current_version


def ensure_cache_ready(engine: SqliteEngine, registry: CacheHandlerRegistry) -> int:
    """
    Назначение:
        Инициализирует базовую схему и таблицы датасетов.
    """
    with engine.transaction():
        version = ensure_base_schema(engine)
        for handler in registry.list():
            handler.ensure_schema(engine)
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
