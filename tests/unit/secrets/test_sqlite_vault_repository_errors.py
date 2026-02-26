from __future__ import annotations

from connector.config.models import AppConfig
from connector.config.projections import to_vault_db_config
import os
import sqlite3
from pathlib import Path

import pytest

from connector.domain.secrets.errors import SecretReadError, SecretStoreError
from connector.domain.secrets.models import VaultProbeRecord
from connector.infra.secrets.sqlite.repository import SqliteVaultRepository
from connector.infra.sqlite.engine import open_sqlite, SqliteEngine


def _build_repo(tmp_path: Path) -> tuple[SqliteVaultRepository, SqliteEngine]:
    engine = open_sqlite(
        to_vault_db_config(AppConfig()),
        str(tmp_path / "cache" / "ankey_vault.sqlite3"),
    )
    return SqliteVaultRepository(engine), engine


def test_schema_changed_retry_is_bounded_and_eventually_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo, engine = _build_repo(tmp_path)
    try:
        original_execute = engine.execute
        state = {"remaining_failures": 2}

        def flaky(sql: str, params=None):
            if "INSERT INTO vault_probe" in sql and state["remaining_failures"] > 0:
                state["remaining_failures"] -= 1
                raise sqlite3.OperationalError("database schema has changed")
            return original_execute(sql, params)

        monkeypatch.setattr(engine, "execute", flaky)

        repo.upsert_probe(
            VaultProbeRecord(
                probe_name="startup",
                ciphertext=b"cipher",
                cipher_algo="FERNET_V1",
                key_version="mk_2026",
                dek_version="dek_v1",
                created_at="2026-02-18T10:00:00+00:00",
                updated_at="2026-02-18T10:00:00+00:00",
            )
        )
        assert state["remaining_failures"] == 0
    finally:
        engine.close()


def test_schema_changed_retry_exhaustion_maps_to_domain_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo, engine = _build_repo(tmp_path)
    try:
        def always_schema_changed(sql: str, params=None):
            raise sqlite3.OperationalError("database schema has changed")

        monkeypatch.setattr(engine, "execute", always_schema_changed)

        with pytest.raises(SecretReadError) as exc_info:
            repo.get_probe(probe_name="startup")

        assert exc_info.value.code == "SECRET_READ_ERROR"
        assert exc_info.value.details["reason"] == "schema_changed"
        assert exc_info.value.details["op"] == "get_probe"
        assert exc_info.value.details["schema_retries"] == 2
    finally:
        engine.close()


def test_busy_timeout_maps_to_store_error_with_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo, engine = _build_repo(tmp_path)
    try:
        def always_locked(sql: str, params=None):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(engine, "execute", always_locked)

        with pytest.raises(SecretStoreError) as exc_info:
            repo.upsert_probe(
                VaultProbeRecord(
                    probe_name="startup",
                    ciphertext=b"cipher",
                    cipher_algo="FERNET_V1",
                    key_version="mk_2026",
                    dek_version="dek_v1",
                    created_at="2026-02-18T10:00:00+00:00",
                    updated_at="2026-02-18T10:00:00+00:00",
                )
            )

        details = exc_info.value.details
        assert exc_info.value.code == "SECRET_STORE_ERROR"
        assert details["reason"] == "busy_timeout"
        assert details["op"] == "upsert_probe"
        assert details["current_pid"] == os.getpid()
        assert details["db_path"]
        assert details["lock_holder_pid"] == "unknown"
    finally:
        engine.close()


def test_busy_timeout_maps_to_read_error_with_diagnostics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    repo, engine = _build_repo(tmp_path)
    try:
        def always_locked(sql: str, params=None):
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(engine, "execute", always_locked)

        with pytest.raises(SecretReadError) as exc_info:
            repo.get_probe(probe_name="startup")

        details = exc_info.value.details
        assert exc_info.value.code == "SECRET_READ_ERROR"
        assert details["reason"] == "busy_timeout"
        assert details["op"] == "get_probe"
        assert details["current_pid"] == os.getpid()
        assert details["db_path"]
        assert details["lock_holder_pid"] == "unknown"
    finally:
        engine.close()
