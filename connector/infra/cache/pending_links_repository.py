from __future__ import annotations

from connector.domain.ports.pending_links_repository import (
    PendingLink,
    PendingLinksRepository,
    PendingRow,
    PendingStatus,
)
from connector.infra.cache.sqlite_engine import SqliteEngine


class SqlitePendingLinksRepository(PendingLinksRepository):
    """
    Назначение/ответственность:
        SQLite реализация pending_links.
    """

    def __init__(self, engine: SqliteEngine):
        self.engine = engine

    def add_pending(
        self,
        dataset: str,
        source_row_id: str,
        field: str,
        lookup_key: str,
        expires_at: str | None,
        payload: str | None = None,
    ) -> int:
        cur = self.engine.execute(
            """
            INSERT INTO pending_links(
                dataset,
                source_row_id,
                field,
                lookup_key,
                status,
                reason,
                attempts,
                created_at,
                last_attempt_at,
                expires_at,
                payload
            )
            VALUES (?, ?, ?, ?, ?, NULL, 0, CURRENT_TIMESTAMP, NULL, ?, ?)
            """,
            (dataset, source_row_id, field, lookup_key, PendingStatus.PENDING.value, expires_at, payload),
        )
        return int(cur.lastrowid)

    def list_pending_for_key(self, dataset: str, lookup_key: str) -> list[PendingLink]:
        rows = self.engine.fetchall(
            """
            SELECT pending_id, dataset, source_row_id, field, lookup_key, status, attempts,
                   created_at, last_attempt_at, expires_at, reason, payload
            FROM pending_links
            WHERE dataset = ? AND lookup_key = ? AND status = ?
            """,
            (dataset, lookup_key, PendingStatus.PENDING.value),
        )
        return [_row_to_pending(row) for row in rows]

    def list_pending_rows(self, dataset: str) -> list[PendingRow]:
        rows = self.engine.fetchall(
            """
            SELECT dataset, source_row_id, payload
            FROM pending_links
            WHERE dataset = ? AND status = ? AND payload IS NOT NULL
            GROUP BY source_row_id
            """,
            (dataset, PendingStatus.PENDING.value),
        )
        return [
            PendingRow(
                dataset=row["dataset"],
                source_row_id=row["source_row_id"],
                payload=row["payload"],
            )
            for row in rows
        ]

    def mark_resolved(self, pending_id: int) -> None:
        self.engine.execute(
            """
            UPDATE pending_links
            SET status = ?, reason = NULL, last_attempt_at = CURRENT_TIMESTAMP
            WHERE pending_id = ?
            """,
            (PendingStatus.RESOLVED.value, pending_id),
        )

    def mark_resolved_for_source(self, source_row_id: str) -> None:
        self.engine.execute(
            """
            UPDATE pending_links
            SET status = ?, reason = NULL, last_attempt_at = CURRENT_TIMESTAMP
            WHERE source_row_id = ? AND status = ?
            """,
            (PendingStatus.RESOLVED.value, source_row_id, PendingStatus.PENDING.value),
        )

    def mark_conflict(self, pending_id: int, reason: str | None = None) -> None:
        self.engine.execute(
            """
            UPDATE pending_links
            SET status = ?, reason = ?, last_attempt_at = CURRENT_TIMESTAMP
            WHERE pending_id = ?
            """,
            (PendingStatus.CONFLICT.value, reason, pending_id),
        )

    def mark_expired(self, pending_id: int, reason: str | None = None) -> None:
        self.engine.execute(
            """
            UPDATE pending_links
            SET status = ?, reason = ?, last_attempt_at = CURRENT_TIMESTAMP
            WHERE pending_id = ?
            """,
            (PendingStatus.EXPIRED.value, reason, pending_id),
        )

    def touch_attempt(self, pending_id: int) -> None:
        self.engine.execute(
            """
            UPDATE pending_links
            SET attempts = attempts + 1, last_attempt_at = CURRENT_TIMESTAMP
            WHERE pending_id = ?
            """,
            (pending_id,),
        )

    def sweep_expired(self, now: str, *, reason: str | None = None) -> list[PendingLink]:
        rows = self.engine.fetchall(
            """
            SELECT pending_id, dataset, source_row_id, field, lookup_key, status, attempts,
                   created_at, last_attempt_at, expires_at, reason, payload
            FROM pending_links
            WHERE status = ? AND expires_at IS NOT NULL AND expires_at <= ?
            """,
            (PendingStatus.PENDING.value, now),
        )
        pending = [_row_to_pending(row) for row in rows]
        if not pending:
            return []
        ids = tuple(item.pending_id for item in pending)
        placeholders = ", ".join("?" for _ in ids)
        self.engine.execute(
            f"""
            UPDATE pending_links
            SET status = ?, reason = ?, last_attempt_at = CURRENT_TIMESTAMP
            WHERE pending_id IN ({placeholders})
            """,
            (PendingStatus.EXPIRED.value, reason, *ids),
        )
        return pending


def _row_to_pending(row) -> PendingLink:
    return PendingLink(
        pending_id=int(row["pending_id"]),
        dataset=row["dataset"],
        source_row_id=row["source_row_id"],
        field=row["field"],
        lookup_key=row["lookup_key"],
        status=row["status"],
        attempts=int(row["attempts"]),
        created_at=row["created_at"],
        last_attempt_at=row["last_attempt_at"],
        expires_at=row["expires_at"],
        reason=row["reason"],
        payload=row["payload"],
    )
