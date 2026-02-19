"""
Назначение:
    Vault-only SQLite schema lifecycle (DDL + schema versioning).
"""

from __future__ import annotations

import sqlite3

from connector.infra.sqlite.engine import SqliteEngine

SCHEMA_VERSION = 1


def ensure_vault_schema(engine: SqliteEngine) -> int:
    """
    Назначение:
        Создать vault schema и зафиксировать версию в `vault_meta`.
    """
    _create_meta(engine)
    current_version = _get_schema_version(engine) or 0

    if current_version == 0:
        _create_vault_tables(engine)
        _set_schema_version(engine, SCHEMA_VERSION)
        return SCHEMA_VERSION

    if current_version < SCHEMA_VERSION:
        _migrate_to_latest(engine, current_version)
        _set_schema_version(engine, SCHEMA_VERSION)
        return SCHEMA_VERSION

    return current_version


def _create_meta(engine: SqliteEngine) -> None:
    engine.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )


def _get_schema_version(engine: SqliteEngine) -> int | None:
    row = engine.fetchone("SELECT value FROM vault_meta WHERE key='schema_version'")
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return None


def _set_schema_version(engine: SqliteEngine, version: int) -> None:
    engine.execute(
        """
        INSERT INTO vault_meta(key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        ("schema_version", str(version)),
    )


def _migrate_to_latest(engine: SqliteEngine, current_version: int) -> None:
    """
    Назначение:
        Применить миграции до SCHEMA_VERSION.

    Примечание:
        На текущем этапе поддерживается только bootstrap до v1.
    """
    if current_version < 1:
        _create_vault_tables(engine)


def _create_vault_tables(engine: SqliteEngine) -> None:
    engine.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_dek (
            dek_version TEXT PRIMARY KEY,
            wrapped_dek BLOB NOT NULL,
            wrap_algo TEXT NOT NULL,
            wrap_key_version TEXT NOT NULL,
            is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0, 1)),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    engine.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_secrets (
            secret_id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset TEXT NOT NULL,
            field TEXT NOT NULL,
            locator_hash TEXT NOT NULL,
            locator_version TEXT NOT NULL,
            run_id TEXT,
            ciphertext BLOB NOT NULL,
            cipher_algo TEXT NOT NULL,
            key_version TEXT NOT NULL,
            dek_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (dek_version) REFERENCES vault_dek(dek_version)
        )
        """
    )
    engine.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_vault_secret_unique_scope
        ON vault_secrets(dataset, field, locator_version, locator_hash, COALESCE(run_id, ''))
        """
    )
    engine.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vault_secret_lookup
        ON vault_secrets(dataset, field, locator_version, locator_hash, run_id)
        """
    )
    engine.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_vault_dek_active
        ON vault_dek(is_active, updated_at)
        """
    )
    engine.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_probe (
            probe_name TEXT PRIMARY KEY,
            ciphertext BLOB NOT NULL,
            cipher_algo TEXT NOT NULL,
            key_version TEXT NOT NULL,
            dek_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
