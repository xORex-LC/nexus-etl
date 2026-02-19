"""
Назначение:
    SQLite-адаптер SecretVaultRepositoryPort.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Callable, ContextManager, Iterator

from connector.domain.ports.secrets.repository import SecretVaultRepositoryPort
from connector.domain.secrets.errors import SecretReadError, SecretStoreError
from connector.domain.secrets.models import VaultDekRecord, VaultProbeRecord, VaultSecretRecord
from connector.infra.secrets.sqlite.db import VaultSqliteDb
from connector.infra.secrets.sqlite.schema import ensure_vault_schema

SQLITE_SCHEMA_MAX_RETRIES = 2


class SqliteVaultRepository(SecretVaultRepositoryPort):
    """
    Назначение:
        Репозиторий секретов/DEK/probe поверх отдельной SQLite vault DB.

    Инварианты:
        - write transaction использует `BEGIN IMMEDIATE`;
        - read-path соблюдает run_id precedence: `exact -> global (NULL)`;
        - lock/schema ошибки маппятся в доменную таксономию без утечки секретов.
    """

    def __init__(self, db: VaultSqliteDb):
        self._db = db
        self._conn = db.conn
        self._transaction_depth = 0
        self._ensure_schema()

    @contextmanager
    def transaction(self) -> ContextManager[None]:
        if self._transaction_depth > 0 or self._conn.in_transaction:
            raise RuntimeError("Nested vault transactions are not supported")

        self._transaction_depth += 1
        try:
            self._execute_write("BEGIN IMMEDIATE", op="transaction_begin")
        except Exception:
            self._transaction_depth = 0
            raise

        try:
            yield
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            self._transaction_depth = 0

    def upsert_secret(self, record: VaultSecretRecord) -> None:
        self._execute_write(
            """
            INSERT INTO vault_secrets(
                dataset,
                field,
                locator_hash,
                locator_version,
                run_id,
                ciphertext,
                cipher_algo,
                key_version,
                dek_version,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT DO UPDATE SET
                ciphertext = excluded.ciphertext,
                cipher_algo = excluded.cipher_algo,
                key_version = excluded.key_version,
                dek_version = excluded.dek_version,
                updated_at = excluded.updated_at
            """,
            (
                record.dataset,
                record.field,
                record.locator_hash,
                record.locator_version,
                record.run_id,
                record.ciphertext,
                record.cipher_algo,
                record.key_version,
                record.dek_version,
                record.created_at,
                record.updated_at,
            ),
            op="upsert_secret",
            details={
                "dataset": record.dataset,
                "field": record.field,
                "run_id": record.run_id,
                "locator_version": record.locator_version,
                "key_version": record.key_version,
            },
        )

    def get_secret(
        self,
        *,
        dataset: str,
        field: str,
        locator_hash: str,
        locator_version: str,
        run_id: str | None,
    ) -> VaultSecretRecord | None:
        if run_id is not None:
            row = self._fetchone_read(
                """
                SELECT
                    secret_id,
                    dataset,
                    field,
                    locator_hash,
                    locator_version,
                    run_id,
                    ciphertext,
                    cipher_algo,
                    key_version,
                    dek_version,
                    created_at,
                    updated_at
                FROM vault_secrets
                WHERE dataset = ?
                  AND field = ?
                  AND locator_hash = ?
                  AND locator_version = ?
                  AND (run_id = ? OR run_id IS NULL)
                ORDER BY CASE WHEN run_id = ? THEN 0 ELSE 1 END,
                         updated_at DESC,
                         secret_id DESC
                LIMIT 1
                """,
                (dataset, field, locator_hash, locator_version, run_id, run_id),
                op="get_secret",
                details={
                    "dataset": dataset,
                    "field": field,
                    "run_id": run_id,
                    "locator_version": locator_version,
                },
            )
        else:
            row = self._fetchone_read(
                """
                SELECT
                    secret_id,
                    dataset,
                    field,
                    locator_hash,
                    locator_version,
                    run_id,
                    ciphertext,
                    cipher_algo,
                    key_version,
                    dek_version,
                    created_at,
                    updated_at
                FROM vault_secrets
                WHERE dataset = ?
                  AND field = ?
                  AND locator_hash = ?
                  AND locator_version = ?
                  AND run_id IS NULL
                ORDER BY updated_at DESC, secret_id DESC
                LIMIT 1
                """,
                (dataset, field, locator_hash, locator_version),
                op="get_secret",
                details={
                    "dataset": dataset,
                    "field": field,
                    "run_id": None,
                    "locator_version": locator_version,
                },
            )

        return _row_to_secret_record(row)

    def delete_secret(
        self,
        *,
        dataset: str,
        field: str,
        locator_hash: str,
        locator_version: str,
        run_id: str | None,
    ) -> int:
        if run_id is None:
            cur = self._execute_write(
                """
                DELETE FROM vault_secrets
                WHERE dataset = ?
                  AND field = ?
                  AND locator_hash = ?
                  AND locator_version = ?
                  AND run_id IS NULL
                """,
                (dataset, field, locator_hash, locator_version),
                op="delete_secret",
                details={
                    "dataset": dataset,
                    "field": field,
                    "run_id": None,
                    "locator_version": locator_version,
                },
            )
            return int(cur.rowcount or 0)

        cur = self._execute_write(
            """
            DELETE FROM vault_secrets
            WHERE dataset = ?
              AND field = ?
              AND locator_hash = ?
              AND locator_version = ?
              AND run_id = ?
            """,
            (dataset, field, locator_hash, locator_version, run_id),
            op="delete_secret",
            details={
                "dataset": dataset,
                "field": field,
                "run_id": run_id,
                "locator_version": locator_version,
            },
        )
        return int(cur.rowcount or 0)

    def upsert_dek(self, record: VaultDekRecord) -> None:
        with self._write_unit():
            if record.is_active:
                self._execute_write(
                    """
                    UPDATE vault_dek
                    SET is_active = 0,
                        updated_at = ?
                    WHERE is_active = 1
                      AND dek_version != ?
                    """,
                    (record.updated_at, record.dek_version),
                    op="deactivate_other_dek",
                    details={"dek_version": record.dek_version},
                )

            self._execute_write(
                """
                INSERT INTO vault_dek(
                    dek_version,
                    wrapped_dek,
                    wrap_algo,
                    wrap_key_version,
                    is_active,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(dek_version) DO UPDATE SET
                    wrapped_dek = excluded.wrapped_dek,
                    wrap_algo = excluded.wrap_algo,
                    wrap_key_version = excluded.wrap_key_version,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """,
                (
                    record.dek_version,
                    record.wrapped_dek,
                    record.wrap_algo,
                    record.wrap_key_version,
                    int(record.is_active),
                    record.created_at,
                    record.updated_at,
                ),
                op="upsert_dek",
                details={
                    "dek_version": record.dek_version,
                    "key_version": record.wrap_key_version,
                },
            )

    def get_dek(self, *, dek_version: str) -> VaultDekRecord | None:
        row = self._fetchone_read(
            """
            SELECT
                dek_version,
                wrapped_dek,
                wrap_algo,
                wrap_key_version,
                is_active,
                created_at,
                updated_at
            FROM vault_dek
            WHERE dek_version = ?
            LIMIT 1
            """,
            (dek_version,),
            op="get_dek",
            details={"dek_version": dek_version},
        )
        return _row_to_dek_record(row)

    def get_active_dek(self) -> VaultDekRecord | None:
        row = self._fetchone_read(
            """
            SELECT
                dek_version,
                wrapped_dek,
                wrap_algo,
                wrap_key_version,
                is_active,
                created_at,
                updated_at
            FROM vault_dek
            WHERE is_active = 1
            ORDER BY updated_at DESC, dek_version DESC
            LIMIT 1
            """,
            None,
            op="get_active_dek",
        )
        return _row_to_dek_record(row)

    def upsert_probe(self, record: VaultProbeRecord) -> None:
        self._execute_write(
            """
            INSERT INTO vault_probe(
                probe_name,
                ciphertext,
                cipher_algo,
                key_version,
                dek_version,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(probe_name) DO UPDATE SET
                ciphertext = excluded.ciphertext,
                cipher_algo = excluded.cipher_algo,
                key_version = excluded.key_version,
                dek_version = excluded.dek_version,
                updated_at = excluded.updated_at
            """,
            (
                record.probe_name,
                record.ciphertext,
                record.cipher_algo,
                record.key_version,
                record.dek_version,
                record.created_at,
                record.updated_at,
            ),
            op="upsert_probe",
            details={"key_version": record.key_version},
        )

    def get_probe(self, *, probe_name: str) -> VaultProbeRecord | None:
        row = self._fetchone_read(
            """
            SELECT
                probe_name,
                ciphertext,
                cipher_algo,
                key_version,
                dek_version,
                created_at,
                updated_at
            FROM vault_probe
            WHERE probe_name = ?
            LIMIT 1
            """,
            (probe_name,),
            op="get_probe",
        )
        return _row_to_probe_record(row)

    def _ensure_schema(self) -> None:
        try:
            ensure_vault_schema(self._conn)
        except sqlite3.DatabaseError as exc:
            raise self._map_store_error(exc, op="schema_bootstrap", extra_details={"stage": "startup"}) from exc

    @contextmanager
    def _write_unit(self) -> Iterator[None]:
        """
        Назначение:
            Выполнить группу write-операций атомарно.
        """
        if self._transaction_depth > 0 or self._conn.in_transaction:
            yield
            return
        with self.transaction():
            yield

    def _execute_write(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        op: str,
        details: dict[str, Any] | None = None,
    ) -> sqlite3.Cursor:
        return self._run_with_schema_retry(
            lambda: self._execute_raw(sql, params),
            op=op,
            read_path=False,
            details=details,
        )

    def _fetchone_read(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        op: str,
        details: dict[str, Any] | None = None,
    ) -> sqlite3.Row | None:
        cursor = self._run_with_schema_retry(
            lambda: self._execute_raw(sql, params),
            op=op,
            read_path=True,
            details=details,
        )
        return cursor.fetchone()

    def _run_with_schema_retry(
        self,
        action: Callable[[], sqlite3.Cursor],
        *,
        op: str,
        read_path: bool,
        details: dict[str, Any] | None = None,
    ) -> sqlite3.Cursor:
        for attempt in range(SQLITE_SCHEMA_MAX_RETRIES + 1):
            try:
                return action()
            except sqlite3.OperationalError as exc:
                if _is_schema_changed(exc) and attempt < SQLITE_SCHEMA_MAX_RETRIES:
                    continue
                if read_path:
                    raise self._map_read_error(exc, op=op, extra_details=details) from exc
                raise self._map_store_error(exc, op=op, extra_details=details) from exc
            except sqlite3.DatabaseError as exc:
                if read_path:
                    raise self._map_read_error(exc, op=op, extra_details=details) from exc
                raise self._map_store_error(exc, op=op, extra_details=details) from exc

        # Защитный блок: цикл всегда завершится return/raise выше.
        raise RuntimeError("Unreachable sqlite retry state")

    def _execute_raw(self, sql: str, params: tuple[Any, ...] | None) -> sqlite3.Cursor:
        if params is None:
            return self._conn.execute(sql)
        return self._conn.execute(sql, params)

    def _map_store_error(
        self,
        exc: sqlite3.DatabaseError,
        *,
        op: str,
        extra_details: dict[str, Any] | None = None,
    ) -> SecretStoreError:
        return SecretStoreError(
            "Failed to store vault data",
            details=self._build_error_details(exc, op=op, extra_details=extra_details),
        )

    def _map_read_error(
        self,
        exc: sqlite3.DatabaseError,
        *,
        op: str,
        extra_details: dict[str, Any] | None = None,
    ) -> SecretReadError:
        return SecretReadError(
            "Failed to read vault data",
            details=self._build_error_details(exc, op=op, extra_details=extra_details),
        )

    def _build_error_details(
        self,
        exc: sqlite3.DatabaseError,
        *,
        op: str,
        extra_details: dict[str, Any] | None,
    ) -> dict[str, Any]:
        reason = "sqlite_error"
        if _is_busy_timeout(exc):
            reason = "busy_timeout"
        elif _is_schema_changed(exc):
            reason = "schema_changed"

        details: dict[str, Any] = {
            "reason": reason,
            "op": op,
            "db_path": self._resolve_db_path(),
            "current_pid": os.getpid(),
            "sqlite_error": str(exc),
        }
        if reason == "schema_changed":
            details["schema_retries"] = SQLITE_SCHEMA_MAX_RETRIES
        if reason == "busy_timeout":
            details["lock_holder_pid"] = "unknown"
        if extra_details:
            details.update(extra_details)
        return details

    def _resolve_db_path(self) -> str:
        try:
            rows = self._conn.execute("PRAGMA database_list").fetchall()
        except Exception:
            return str(self._db.db_path)
        for row in rows:
            name = row[1]
            file_path = row[2]
            if name == "main" and file_path:
                return str(file_path)
        return str(self._db.db_path)


def _row_to_secret_record(row: sqlite3.Row | None) -> VaultSecretRecord | None:
    if row is None:
        return None
    return VaultSecretRecord(
        dataset=str(row["dataset"]),
        field=str(row["field"]),
        locator_hash=str(row["locator_hash"]),
        locator_version=str(row["locator_version"]),
        ciphertext=row["ciphertext"],
        cipher_algo=str(row["cipher_algo"]),
        key_version=str(row["key_version"]),
        dek_version=str(row["dek_version"]),
        run_id=str(row["run_id"]) if row["run_id"] is not None else None,
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
        secret_id=int(row["secret_id"]) if row["secret_id"] is not None else None,
    )


def _row_to_dek_record(row: sqlite3.Row | None) -> VaultDekRecord | None:
    if row is None:
        return None
    return VaultDekRecord(
        dek_version=str(row["dek_version"]),
        wrapped_dek=row["wrapped_dek"],
        wrap_algo=str(row["wrap_algo"]),
        wrap_key_version=str(row["wrap_key_version"]),
        is_active=bool(int(row["is_active"])),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _row_to_probe_record(row: sqlite3.Row | None) -> VaultProbeRecord | None:
    if row is None:
        return None
    return VaultProbeRecord(
        probe_name=str(row["probe_name"]),
        ciphertext=row["ciphertext"],
        cipher_algo=str(row["cipher_algo"]),
        key_version=str(row["key_version"]),
        dek_version=str(row["dek_version"]),
        created_at=str(row["created_at"]),
        updated_at=str(row["updated_at"]),
    )


def _is_schema_changed(exc: sqlite3.DatabaseError) -> bool:
    error_code = getattr(exc, "sqlite_errorcode", None)
    if error_code == sqlite3.SQLITE_SCHEMA:
        return True
    return "schema has changed" in str(exc).lower()


def _is_busy_timeout(exc: sqlite3.DatabaseError) -> bool:
    error_code = getattr(exc, "sqlite_errorcode", None)
    if error_code in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}:
        return True
    message = str(exc).lower()
    return "database is locked" in message or "database is busy" in message
