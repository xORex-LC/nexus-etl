from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Any, Iterable

from connector.domain.ports.cache.models import CacheMeta, PendingLink, PendingRow, PendingStatus, UpsertResult
from connector.infra.cache.cache_spec import CacheSpec, FieldSpec
from connector.infra.cache.handlers.generic_handler import GenericCacheHandler
from connector.infra.cache.schema import ensure_cache_ready
from connector.infra.cache.sqlite_engine import SqliteEngine


class SqliteCacheGateway:
    """
    Назначение:
        Единый SQLite адаптер cache слоя.

    Ответственность:
        - cache admin + lookup операции;
        - identity/runtime-state операции;
        - pending lifecycle операции.
    """

    def __init__(self, *, engine: SqliteEngine, cache_specs: Iterable[CacheSpec]) -> None:
        self.engine = engine
        self._cache_specs = list(cache_specs)
        ensure_cache_ready(self.engine, self._cache_specs)
        self._handlers = _build_handlers(self._cache_specs)

    # Cache admin + lookup
    def transaction(self) -> AbstractContextManager[None]:
        return self.engine.transaction()

    def upsert(self, dataset: str, write_model: dict) -> UpsertResult:
        handler = _get_handler(self._handlers, dataset)
        return handler.upsert(self.engine, write_model)

    def count(self, dataset: str) -> int:
        handler = _get_handler(self._handlers, dataset)
        return handler.count_total(self.engine)

    def count_by_table(self, dataset: str) -> dict[str, int]:
        handler = _get_handler(self._handlers, dataset)
        return handler.count_by_table(self.engine)

    def clear(self, dataset: str) -> None:
        handler = _get_handler(self._handlers, dataset)
        handler.clear(self.engine)

    def list_datasets(self) -> list[str]:
        return list(self._handlers.keys())

    def get_meta(self, dataset: str | None = None) -> CacheMeta:
        if dataset is None:
            rows = self.engine.fetchall("SELECT key, value FROM meta")
            return CacheMeta({row[0]: row[1] for row in rows})
        rows = self.engine.fetchall("SELECT key, value FROM meta WHERE key LIKE ?", (f"{dataset}.%",))
        values: dict[str, str | None] = {}
        for row in rows:
            key = row[0].split(".", 1)[1] if "." in row[0] else row[0]
            values[key] = row[1]
        return CacheMeta(values)

    def set_meta(self, dataset: str | None, key: str, value: str | None) -> None:
        full_key = key if dataset is None else f"{dataset}.{key}"
        if value is None:
            self.engine.execute("DELETE FROM meta WHERE key = ?", (full_key,))
            return
        self.engine.execute(
            """
            INSERT INTO meta(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value=excluded.value
            """,
            (full_key, value),
        )

    def reset_meta(self, dataset: str) -> None:
        self.engine.execute("DELETE FROM meta WHERE key LIKE ?", (f"{dataset}.%",))

    def find(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> list[dict]:
        handler = _get_handler(self._handlers, dataset)
        spec = getattr(handler, "spec", None)
        if spec is None:
            raise ValueError(f"Cache handler for dataset '{dataset}' does not expose spec")

        field_map = _build_field_map(spec.fields)
        if not filters:
            raise ValueError("find() requires at least one filter")

        where_parts: list[str] = []
        params: list[Any] = []

        for key, value in filters.items():
            if key not in field_map:
                raise ValueError(f"Unknown cache field '{key}' for dataset '{dataset}'")
            field_name = field_map[key]
            clause, clause_params = _build_clause(field_name, value, mode)
            if clause is None:
                return []
            where_parts.append(clause)
            params.extend(clause_params)

        if not include_deleted and "deletion_date" in field_map:
            where_parts.append("deletion_date IS NULL")

        where_sql = " AND ".join(where_parts) if where_parts else "1=1"
        rows = self.engine.fetchall(f"SELECT * FROM {spec.table} WHERE {where_sql}", tuple(params))
        return _rows_to_dicts(rows)

    def find_one(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> dict | None:
        results = self.find(dataset, filters, include_deleted=include_deleted, mode=mode)
        return results[0] if results else None

    # Identity/runtime state
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

    # Pending lifecycle
    def add_pending(
        self,
        dataset: str,
        source_row_id: str,
        field: str,
        lookup_key: str,
        expires_at: str | None,
        payload: str | None = None,
    ) -> int:
        existing = self.engine.fetchone(
            """
            SELECT pending_id
            FROM pending_links
            WHERE dataset = ? AND source_row_id = ? AND field = ? AND lookup_key = ? AND status = ?
            """,
            (dataset, source_row_id, field, lookup_key, PendingStatus.PENDING.value),
        )
        if existing is not None:
            pending_id = int(existing[0])
            if payload is not None or expires_at is not None:
                self.engine.execute(
                    """
                    UPDATE pending_links
                    SET payload = COALESCE(?, payload),
                        expires_at = COALESCE(?, expires_at),
                        last_attempt_at = CURRENT_TIMESTAMP
                    WHERE pending_id = ?
                    """,
                    (payload, expires_at, pending_id),
                )
            return pending_id

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

    def touch_attempt(self, pending_id: int) -> int:
        self.engine.execute(
            """
            UPDATE pending_links
            SET attempts = attempts + 1, last_attempt_at = CURRENT_TIMESTAMP
            WHERE pending_id = ?
            """,
            (pending_id,),
        )
        row = self.engine.fetchone(
            "SELECT attempts FROM pending_links WHERE pending_id = ?",
            (pending_id,),
        )
        return int(row[0]) if row is not None else 0

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

    def purge_stale(
        self,
        cutoff: str,
        statuses: tuple[str, ...] | None = None,
    ) -> int:
        eff_statuses = statuses or (
            PendingStatus.RESOLVED.value,
            PendingStatus.EXPIRED.value,
            PendingStatus.CONFLICT.value,
        )
        placeholders = ", ".join("?" for _ in eff_statuses)
        row = self.engine.execute(
            f"""
            DELETE FROM pending_links
            WHERE status IN ({placeholders})
              AND COALESCE(last_attempt_at, created_at) IS NOT NULL
              AND COALESCE(last_attempt_at, created_at) <= ?
            """,
            (*eff_statuses, cutoff),
        )
        return int(row.rowcount or 0)


def _build_handlers(cache_specs: list[CacheSpec]) -> dict[str, GenericCacheHandler]:
    handlers: dict[str, GenericCacheHandler] = {}
    for spec in cache_specs:
        if spec.dataset in handlers:
            raise ValueError(f"Duplicate cache spec for dataset: {spec.dataset}")
        handlers[spec.dataset] = GenericCacheHandler(spec)
    return handlers


def _get_handler(handlers: dict[str, GenericCacheHandler], dataset: str) -> GenericCacheHandler:
    if dataset not in handlers:
        raise ValueError(f"Unsupported cache dataset: {dataset}")
    return handlers[dataset]


def _rows_to_dicts(rows: list[Any]) -> list[dict]:
    result: list[dict] = []
    for row in rows:
        if row is None:
            continue
        if hasattr(row, "keys"):
            result.append({k: row[k] for k in row.keys()})
        else:
            result.append(dict(row))
    return result


def _build_field_map(fields: tuple[FieldSpec, ...]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for field in fields:
        mapping[field.name] = field.name
        if field.source:
            mapping[field.source] = field.name
    return mapping


def _build_clause(field_name: str, value: Any, mode: str) -> tuple[str | None, list[Any]]:
    if mode == "exact":
        return f"{field_name} = ?", [value]
    if mode == "like":
        return f"{field_name} LIKE ?", [value]
    if mode == "in":
        if value is None:
            return None, []
        if isinstance(value, (list, tuple, set)):
            value_list = list(value)
        else:
            value_list = [value]
        if not value_list:
            return None, []
        placeholders = ", ".join("?" for _ in value_list)
        return f"{field_name} IN ({placeholders})", value_list
    raise ValueError(f"Unsupported search mode: {mode}")


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
