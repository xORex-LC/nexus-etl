"""
Назначение:
    DDL для identity-таблиц (identity_index, pending_links, identity_runtime_state)
    в отдельной identity.sqlite3 базе.

Граница ответственности:
    - Только DDL и обеспечение существования таблиц и индексов.
    - Не содержит миграций (данные в identity DB не переносятся — чистая схема).
    - Не знает о cache-слое и его схемах.
"""
from __future__ import annotations

from connector.infra.sqlite.engine import SqliteEngine


def ensure_identity_schema(engine: SqliteEngine) -> None:
    """
    Назначение:
        Создать identity-таблицы и индексы если они ещё не существуют.

    Алгоритм:
        1. identity_index — маппинг identity_key → resolved_id per dataset.
        2. pending_links — ссылки в ожидании разрешения, с lookup_key и статусом.
        3. identity_runtime_state — scoped ephemeral state (match/resolve run).
    """
    _create_identity_index(engine)
    _create_pending_links(engine)
    _create_identity_runtime_state(engine)


def _create_identity_index(engine: SqliteEngine) -> None:
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


def _create_pending_links(engine: SqliteEngine) -> None:
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
    engine.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pending_replay_rows
        ON pending_links(dataset, status, source_row_id, last_attempt_at, created_at, pending_id)
        """
    )


def _create_identity_runtime_state(engine: SqliteEngine) -> None:
    engine.execute(
        """
        CREATE TABLE IF NOT EXISTS identity_runtime_state (
            scope TEXT NOT NULL,
            dataset TEXT NOT NULL,
            state_key TEXT NOT NULL,
            state_value TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (scope, dataset, state_key)
        )
        """
    )
    engine.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_identity_runtime_scope
        ON identity_runtime_state(scope, dataset)
        """
    )
