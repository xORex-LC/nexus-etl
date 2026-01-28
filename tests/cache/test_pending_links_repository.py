from __future__ import annotations

import sqlite3

from connector.infra.cache.pending_links_repository import SqlitePendingLinksRepository
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine


def _make_engine() -> SqliteEngine:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    engine = SqliteEngine(conn)
    ensure_cache_ready(engine, [])
    return engine


def test_purge_stale_removes_only_processed_statuses():
    engine = _make_engine()
    repo = SqlitePendingLinksRepository(engine)

    pending_id = repo.add_pending("employees", "row-p", "manager_id", "k1", None)
    resolved_old_id = repo.add_pending("employees", "row-r-old", "manager_id", "k2", None)
    expired_old_id = repo.add_pending("employees", "row-e-old", "manager_id", "k3", None)
    conflict_old_id = repo.add_pending("employees", "row-c-old", "manager_id", "k4", None)
    resolved_new_id = repo.add_pending("employees", "row-r-new", "manager_id", "k5", None)

    repo.mark_resolved(resolved_old_id)
    repo.mark_expired(expired_old_id, reason="expired")
    repo.mark_conflict(conflict_old_id, reason="conflict")
    repo.mark_resolved(resolved_new_id)

    old_ts = "2000-01-01T00:00:00+00:00"
    new_ts = "2099-01-01T00:00:00+00:00"
    for pending_id_to_update in (resolved_old_id, expired_old_id, conflict_old_id):
        engine.execute(
            "UPDATE pending_links SET last_attempt_at = ?, created_at = ? WHERE pending_id = ?",
            (old_ts, old_ts, pending_id_to_update),
        )
    engine.execute(
        "UPDATE pending_links SET last_attempt_at = ?, created_at = ? WHERE pending_id = ?",
        (new_ts, new_ts, resolved_new_id),
    )
    engine.execute(
        "UPDATE pending_links SET created_at = ? WHERE pending_id = ?",
        (old_ts, pending_id),
    )

    purged = repo.purge_stale("2020-01-01T00:00:00+00:00")
    assert purged == 3

    statuses = [row[0] for row in engine.fetchall("SELECT status FROM pending_links ORDER BY pending_id")]
    assert statuses == ["pending", "resolved"]
