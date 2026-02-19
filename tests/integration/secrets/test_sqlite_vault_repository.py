from __future__ import annotations

from pathlib import Path

import pytest

from connector.config.app_settings import SqliteSettings, build_vault_db_config
from connector.domain.secrets.models import VaultDekRecord, VaultProbeRecord, VaultSecretRecord
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.secrets.sqlite.schema import SCHEMA_VERSION
from connector.infra.sqlite.engine import open_sqlite, SqliteEngine


def _build_repo(tmp_path: Path) -> tuple[SqliteVaultRepository, SqliteEngine]:
    engine = open_sqlite(
        build_vault_db_config(SqliteSettings()),
        str(tmp_path / "cache" / "ankey_vault.sqlite3"),
    )
    return SqliteVaultRepository(engine), engine


def test_schema_bootstrap_creates_vault_tables(tmp_path: Path):
    repo, engine = _build_repo(tmp_path)
    try:
        table_rows = engine.fetchall(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table'
              AND name LIKE 'vault_%'
            """
        )
        table_names = {row[0] for row in table_rows}

        assert "vault_meta" in table_names
        assert "vault_dek" in table_names
        assert "vault_secrets" in table_names
        assert "vault_probe" in table_names

        version_row = engine.fetchone("SELECT value FROM vault_meta WHERE key='schema_version'")
        assert version_row is not None
        assert version_row[0] == str(SCHEMA_VERSION)
    finally:
        engine.close()


def test_secret_upsert_last_write_wins_and_run_id_precedence(tmp_path: Path):
    repo, engine = _build_repo(tmp_path)
    try:
        repo.upsert_dek(
            VaultDekRecord(
                dek_version="dek_v1",
                wrapped_dek=b"wrapped-dek",
                wrap_algo="FERNET_V1",
                wrap_key_version="mk_2026",
                is_active=True,
                created_at="2026-02-18T10:00:00+00:00",
                updated_at="2026-02-18T10:00:00+00:00",
            )
        )

        repo.upsert_secret(
            VaultSecretRecord(
                dataset="employees",
                field="password",
                locator_hash="loc-v1",
                locator_version="v1",
                ciphertext=b"global-secret",
                cipher_algo="FERNET_V1",
                key_version="mk_2026",
                dek_version="dek_v1",
                run_id=None,
                created_at="2026-02-18T10:01:00+00:00",
                updated_at="2026-02-18T10:01:00+00:00",
            )
        )
        repo.upsert_secret(
            VaultSecretRecord(
                dataset="employees",
                field="password",
                locator_hash="loc-v1",
                locator_version="v1",
                ciphertext=b"run-secret",
                cipher_algo="FERNET_V1",
                key_version="mk_2026",
                dek_version="dek_v1",
                run_id="run-1",
                created_at="2026-02-18T10:02:00+00:00",
                updated_at="2026-02-18T10:02:00+00:00",
            )
        )

        for_run = repo.get_secret(
            dataset="employees",
            field="password",
            locator_hash="loc-v1",
            locator_version="v1",
            run_id="run-1",
        )
        assert for_run is not None
        assert for_run.ciphertext == b"run-secret"
        assert for_run.run_id == "run-1"

        fallback = repo.get_secret(
            dataset="employees",
            field="password",
            locator_hash="loc-v1",
            locator_version="v1",
            run_id="run-2",
        )
        assert fallback is not None
        assert fallback.ciphertext == b"global-secret"
        assert fallback.run_id is None

        repo.upsert_secret(
            VaultSecretRecord(
                dataset="employees",
                field="password",
                locator_hash="loc-v1",
                locator_version="v1",
                ciphertext=b"run-secret-updated",
                cipher_algo="FERNET_V1",
                key_version="mk_2026",
                dek_version="dek_v1",
                run_id="run-1",
                created_at="2026-02-18T10:02:00+00:00",
                updated_at="2026-02-18T10:03:00+00:00",
            )
        )
        updated = repo.get_secret(
            dataset="employees",
            field="password",
            locator_hash="loc-v1",
            locator_version="v1",
            run_id="run-1",
        )
        assert updated is not None
        assert updated.ciphertext == b"run-secret-updated"

        deleted_scoped = repo.delete_secret(
            dataset="employees",
            field="password",
            locator_hash="loc-v1",
            locator_version="v1",
            run_id="run-1",
        )
        assert deleted_scoped == 1
        after_delete = repo.get_secret(
            dataset="employees",
            field="password",
            locator_hash="loc-v1",
            locator_version="v1",
            run_id="run-1",
        )
        assert after_delete is not None
        assert after_delete.run_id is None
        assert after_delete.ciphertext == b"global-secret"

        deleted_global = repo.delete_secret(
            dataset="employees",
            field="password",
            locator_hash="loc-v1",
            locator_version="v1",
            run_id=None,
        )
        assert deleted_global == 1
        assert (
            repo.get_secret(
                dataset="employees",
                field="password",
                locator_hash="loc-v1",
                locator_version="v1",
                run_id="run-9",
            )
            is None
        )
    finally:
        engine.close()


def test_dek_upsert_keeps_single_active_dek(tmp_path: Path):
    repo, engine = _build_repo(tmp_path)
    try:
        repo.upsert_dek(
            VaultDekRecord(
                dek_version="dek_v1",
                wrapped_dek=b"wrapped-1",
                wrap_algo="FERNET_V1",
                wrap_key_version="mk_2025",
                is_active=True,
                created_at="2026-02-18T10:00:00+00:00",
                updated_at="2026-02-18T10:00:00+00:00",
            )
        )
        repo.upsert_dek(
            VaultDekRecord(
                dek_version="dek_v2",
                wrapped_dek=b"wrapped-2",
                wrap_algo="FERNET_V1",
                wrap_key_version="mk_2026",
                is_active=True,
                created_at="2026-02-18T10:01:00+00:00",
                updated_at="2026-02-18T10:01:00+00:00",
            )
        )

        active = repo.get_active_dek()
        old = repo.get_dek(dek_version="dek_v1")
        new = repo.get_dek(dek_version="dek_v2")

        assert active is not None
        assert active.dek_version == "dek_v2"
        assert new is not None and new.is_active is True
        assert old is not None and old.is_active is False
    finally:
        engine.close()


def test_probe_roundtrip(tmp_path: Path):
    repo, engine = _build_repo(tmp_path)
    try:
        probe = VaultProbeRecord(
            probe_name="startup",
            ciphertext=b"probe-cipher",
            cipher_algo="FERNET_V1",
            key_version="mk_2026",
            dek_version="dek_v1",
            created_at="2026-02-18T10:00:00+00:00",
            updated_at="2026-02-18T10:00:00+00:00",
        )

        repo.upsert_probe(probe)
        stored = repo.get_probe(probe_name="startup")

        assert stored is not None
        assert stored.probe_name == "startup"
        assert stored.ciphertext == b"probe-cipher"
    finally:
        engine.close()


def test_repository_rejects_nested_transactions(tmp_path: Path):
    repo, engine = _build_repo(tmp_path)
    try:
        with repo.transaction():
            with pytest.raises(RuntimeError, match="Nested vault transactions"):
                with repo.transaction():
                    pass
    finally:
        engine.close()
