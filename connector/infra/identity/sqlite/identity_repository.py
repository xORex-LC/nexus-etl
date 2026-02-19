from __future__ import annotations

from connector.infra.sqlite.engine import SqliteEngine


class SqliteIdentityRepository:
    """
    Назначение/ответственность:
        SQLite реализация identity_index и identity_runtime_state.
        Работает с identity.sqlite3 через SqliteEngine.
    """

    def __init__(self, engine: SqliteEngine):
        self.engine = engine

    def upsert_identity(self, dataset: str, identity_key: str, resolved_id: str) -> None:
        self.engine.execute(
            """
            INSERT INTO identity_index(dataset, identity_key, resolved_id, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(dataset, identity_key, resolved_id)
            DO UPDATE SET updated_at=CURRENT_TIMESTAMP
            """,
            (dataset, identity_key, resolved_id),
        )

    def find_candidates(self, dataset: str, identity_key: str) -> list[str]:
        rows = self.engine.fetchall(
            "SELECT resolved_id FROM identity_index WHERE dataset = ? AND identity_key = ?",
            (dataset, identity_key),
        )
        return [str(row[0]) for row in rows]

    def set_runtime_state(
        self,
        scope: str,
        dataset: str,
        state_key: str,
        state_value: str,
    ) -> None:
        self.engine.execute(
            """
            INSERT INTO identity_runtime_state(scope, dataset, state_key, state_value, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(scope, dataset, state_key)
            DO UPDATE SET state_value=excluded.state_value, updated_at=CURRENT_TIMESTAMP
            """,
            (scope, dataset, state_key, state_value),
        )

    def get_runtime_state(
        self,
        scope: str,
        dataset: str,
        state_key: str,
    ) -> str | None:
        row = self.engine.fetchone(
            """
            SELECT state_value
            FROM identity_runtime_state
            WHERE scope = ? AND dataset = ? AND state_key = ?
            """,
            (scope, dataset, state_key),
        )
        if row is None:
            return None
        value = row[0]
        return str(value) if value is not None else None

    def clear_runtime_scope(self, scope: str) -> None:
        self.engine.execute("DELETE FROM identity_runtime_state WHERE scope = ?", (scope,))
