"""
Назначение:
    Vault-only SQLite schema lifecycle (DDL + schema versioning).

Граница ответственности:
    - Создаёт/поддерживает актуальную схему vault SQLite.
    - Не выполняет инкрементальные data migrations между версиями:
      при несовпадении schema_version применяется reset-политика
      (данные vault-таблиц удаляются, схема пересоздаётся).
"""

from __future__ import annotations

from connector.infra.sqlite.engine import SqliteEngine

SCHEMA_VERSION = 3


def ensure_vault_schema(engine: SqliteEngine) -> int:
    """
    Назначение:
        Создать vault schema и зафиксировать версию в `vault_meta`.

    Контракт:
        - bootstrap (`schema_version` отсутствует): создаются все таблицы;
        - matching version: выполняется idempotent `CREATE TABLE IF NOT EXISTS`;
        - version mismatch: выполняется destructive reset схемы
          (drop vault tables -> create tables), затем фиксируется текущая версия.
    """
    _create_meta(engine)
    current_version = _get_schema_version(engine) or 0

    if current_version == 0:
        _create_vault_tables(engine)
        _set_schema_version(engine, SCHEMA_VERSION)
        return SCHEMA_VERSION

    if current_version != SCHEMA_VERSION:
        _reset_vault_schema(engine)
        _set_schema_version(engine, SCHEMA_VERSION)
        return SCHEMA_VERSION

    _create_vault_tables(engine)
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


def _reset_vault_schema(engine: SqliteEngine) -> None:
    """Сбросить vault-схему (drop + create) при несовместимой версии."""
    _drop_vault_tables(engine)
    _create_vault_tables(engine)


def _create_vault_tables(engine: SqliteEngine) -> None:
    """Создать полный набор vault-таблиц для bootstrap нового хранилища."""
    _create_vault_core_tables(engine)
    _create_vault_unseal_meta_table(engine)
    _create_vault_management_meta_table(engine)


def _create_vault_core_tables(engine: SqliteEngine) -> None:
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


def _create_vault_management_meta_table(engine: SqliteEngine) -> None:
    """Создать key-value таблицу служебного lifecycle metadata vault-management."""
    engine.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_management_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
        """
    )


def _create_vault_unseal_meta_table(engine: SqliteEngine) -> None:
    """Создать metadata-таблицу unseal-модели master wrapping key."""
    engine.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_unseal_meta (
            id INTEGER PRIMARY KEY CHECK(id = 1),
            key_version TEXT NOT NULL,
            kdf_algo TEXT NOT NULL,
            kdf_salt BLOB NOT NULL,
            kdf_time_cost INTEGER NOT NULL,
            kdf_memory_cost_kib INTEGER NOT NULL,
            kdf_parallelism INTEGER NOT NULL,
            kdf_hash_len INTEGER NOT NULL,
            hmac_algo TEXT NOT NULL,
            hmac_salt BLOB NOT NULL,
            hmac_digest BLOB NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )


def _drop_vault_tables(engine: SqliteEngine) -> None:
    """Удалить все vault-таблицы данных для полной пересборки схемы."""
    engine.execute("DROP TABLE IF EXISTS vault_probe")
    engine.execute("DROP TABLE IF EXISTS vault_secrets")
    engine.execute("DROP TABLE IF EXISTS vault_dek")
    engine.execute("DROP TABLE IF EXISTS vault_unseal_meta")
    engine.execute("DROP TABLE IF EXISTS vault_management_meta")
