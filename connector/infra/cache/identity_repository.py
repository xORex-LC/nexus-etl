from __future__ import annotations

from connector.domain.ports.identity_repository import IdentityRepository
from connector.infra.cache.sqlite_engine import SqliteEngine


class SqliteIdentityRepository(IdentityRepository):
    """
    Назначение/ответственность:
        SQLite реализация identity_index.
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
