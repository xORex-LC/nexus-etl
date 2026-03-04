"""
Назначение:
    SQLite-адаптер SecretVaultRepositoryPort поверх SqliteEngine.

Граница ответственности:
    - Реализует SecretVaultRepositoryPort: CRUD для secrets, DEK, probe и lifecycle metadata.
    - Отображает sqlite3-исключения в доменную таксономию (SecretStoreError / SecretReadError).
    - Не знает о ключевом материале, шифровании и доменных сервисах.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from connector.domain.ports.secrets.repository import SecretVaultRepositoryPort
from connector.domain.secrets.errors import SecretReadError, SecretStoreError
from connector.domain.secrets.models import VaultDekRecord, VaultProbeRecord, VaultSecretRecord
from connector.infra.secrets.sqlite.schema import ensure_vault_schema
from connector.infra.sqlite.engine import SqliteEngine

SQLITE_SCHEMA_MAX_RETRIES = 2


class SqliteVaultRepository(SecretVaultRepositoryPort):
    """
    Назначение:
        Репозиторий секретов/DEK/probe поверх отдельной SQLite vault DB.

    Инварианты:
        - write transaction использует `BEGIN IMMEDIATE`;
        - read-path соблюдает run_id precedence: `exact -> global (NULL)`;
        - lifecycle metadata хранится в `vault_management_meta` (key-value);
        - lock/schema ошибки маппятся в доменную таксономию без утечки секретов.
    """

    def __init__(self, engine: SqliteEngine):
        self._engine = engine
        self._ensure_schema()

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """
        Назначение:
            Открыть явную vault-транзакцию (BEGIN IMMEDIATE).

        Raises:
            RuntimeError: при попытке вложенной транзакции.
            SecretStoreError: при SQLite-ошибке (включая readonly storage).
        """
        try:
            with self._engine.transaction(mode="immediate"):
                yield
        except RuntimeError as exc:
            # Переформатируем nested-ошибку в vault-специфичное сообщение
            # для обратной совместимости с кодом, проверяющим "Nested vault transactions".
            if "Nested" in str(exc):
                raise RuntimeError("Nested vault transactions are not supported") from exc
            raise
        except sqlite3.DatabaseError as exc:
            # Маппим SQLite-ошибки (включая readonly) в SecretStoreError,
            # чтобы VaultStartupGuard._is_storage_readonly() мог их распознать.
            raise self._map_store_error(exc, op="transaction_begin") from exc

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
        with self._engine.autobegin():
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

    def get_last_rotated_at(self) -> str | None:
        """
        Назначение:
            Вернуть timestamp последней успешной ротации (`last_rotated_at`) из meta.
        """
        return self._get_meta_value("last_rotated_at")

    def set_last_rotated_at(self, iso_utc: str) -> None:
        """
        Назначение:
            Зафиксировать timestamp последней успешной ротации в key-value meta.
        """
        self._set_meta_value("last_rotated_at", iso_utc)

    def set_last_rotation_result(self, *, result: str, reason: str | None = None) -> None:
        """
        Назначение:
            Обновить служебный статус последней lifecycle-операции ротации.

        Контракт:
            - `last_rotation_result` записывается всегда;
            - `last_rotation_reason` обновляется при наличии reason;
            - `last_rotation_reason` удаляется, если reason=None.
        """
        with self._engine.autobegin():
            self._set_meta_value("last_rotation_result", result)
            if reason is None:
                self._delete_meta_value("last_rotation_reason")
            else:
                self._set_meta_value("last_rotation_reason", reason)

    def _ensure_schema(self) -> None:
        try:
            ensure_vault_schema(self._engine)
        except sqlite3.DatabaseError as exc:
            raise self._map_store_error(exc, op="schema_bootstrap", extra_details={"stage": "startup"}) from exc

    def _get_meta_value(self, key: str) -> str | None:
        row = self._fetchone_read(
            """
            SELECT value
            FROM vault_management_meta
            WHERE key = ?
            LIMIT 1
            """,
            (key,),
            op="get_vault_management_meta",
            details={"meta_key": key},
        )
        if row is None:
            return None
        value = row["value"]
        return str(value) if value is not None else None

    def _set_meta_value(self, key: str, value: str) -> None:
        self._execute_write(
            """
            INSERT INTO vault_management_meta(key, value)
            VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
            op="set_vault_management_meta",
            details={"meta_key": key},
        )

    def _delete_meta_value(self, key: str) -> None:
        self._execute_write(
            """
            DELETE FROM vault_management_meta
            WHERE key = ?
            """,
            (key,),
            op="delete_vault_management_meta",
            details={"meta_key": key},
        )

    def _execute_write(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        op: str,
        details: dict[str, Any] | None = None,
    ) -> sqlite3.Cursor:
        try:
            return self._engine.execute_with_retry(sql, params, max_retries=SQLITE_SCHEMA_MAX_RETRIES)
        except sqlite3.DatabaseError as exc:
            raise self._map_store_error(exc, op=op, extra_details=details) from exc

    def _fetchone_read(
        self,
        sql: str,
        params: tuple[Any, ...] | None = None,
        *,
        op: str,
        details: dict[str, Any] | None = None,
    ) -> sqlite3.Row | None:
        try:
            return self._engine.execute_with_retry(sql, params, max_retries=SQLITE_SCHEMA_MAX_RETRIES).fetchone()
        except sqlite3.DatabaseError as exc:
            raise self._map_read_error(exc, op=op, extra_details=details) from exc

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
            "db_path": self._engine.db_path,
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
