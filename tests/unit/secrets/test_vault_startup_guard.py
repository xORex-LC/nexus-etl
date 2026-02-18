from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet
import pytest

from connector.domain.secrets.errors import (
    SecretStoreError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)
from connector.domain.secrets.vault_startup_guard import DEFAULT_PROBE_NAME, VaultStartupGuard
from connector.infra.secrets import EnvVaultKeyProvider, FernetEnvelopeCipher
from connector.infra.secrets.sqlite import SqliteVaultRepository, VaultSqliteDb


def _new_key() -> str:
    return Fernet.generate_key().decode("utf-8")


def _build_guard(*, repository, key_material: str, key_version: str = "mk_2026") -> VaultStartupGuard:
    key_provider = EnvVaultKeyProvider(env={"ANKEY_VAULT_MASTER_KEYS": f"{key_version}:{key_material}"})
    return VaultStartupGuard(
        repository=repository,
        cipher=FernetEnvelopeCipher(),
        key_provider=key_provider,
    )


def _build_repo(tmp_path: Path) -> tuple[SqliteVaultRepository, VaultSqliteDb]:
    db = VaultSqliteDb(db_path=str(tmp_path / "cache" / "ankey_vault.sqlite3"))
    return SqliteVaultRepository(db), db


class _ReadonlyRepository:
    """
    Тестовый адаптер readonly storage: write-capability probe всегда проваливается.
    """

    def __init__(self, delegate: SqliteVaultRepository) -> None:
        self._delegate = delegate

    def transaction(self):
        raise SecretStoreError(
            "Failed to store vault data",
            details={"reason": "readonly_storage", "sqlite_error": "attempt to write a readonly database"},
        )

    def __getattr__(self, item):
        return getattr(self._delegate, item)


def test_startup_guard_creates_probe_when_absent_and_storage_writable(tmp_path: Path):
    repo, db = _build_repo(tmp_path)
    try:
        guard = _build_guard(repository=repo, key_material=_new_key())

        guard.ensure_ready()

        stored_probe = repo.get_probe(probe_name=DEFAULT_PROBE_NAME)
        assert stored_probe is not None
        assert stored_probe.probe_name == DEFAULT_PROBE_NAME
        assert repo.get_active_dek() is not None
    finally:
        db.close()


def test_startup_guard_fails_when_probe_absent_and_storage_readonly(tmp_path: Path):
    repo, db = _build_repo(tmp_path)
    try:
        guard = _build_guard(repository=_ReadonlyRepository(repo), key_material=_new_key())

        with pytest.raises(VaultStartupUninitializedReadonlyError) as exc_info:
            guard.ensure_ready()

        assert exc_info.value.code == "VAULT_STARTUP_UNINITIALIZED_READONLY"
        assert exc_info.value.details["reason"] == "probe_missing"
    finally:
        db.close()


def test_startup_guard_fails_on_corrupted_probe(tmp_path: Path):
    repo, db = _build_repo(tmp_path)
    try:
        guard = _build_guard(repository=repo, key_material=_new_key())
        guard.ensure_ready()

        db.conn.execute(
            "UPDATE vault_probe SET ciphertext = ? WHERE probe_name = ?",
            (b"", DEFAULT_PROBE_NAME),
        )
        db.conn.commit()

        with pytest.raises(VaultStartupProbeCorruptedError) as exc_info:
            guard.ensure_ready()

        assert exc_info.value.code == "VAULT_STARTUP_PROBE_CORRUPTED"
        assert exc_info.value.details["reason"] == "probe_ciphertext_missing"
    finally:
        db.close()


def test_startup_guard_fails_when_probe_cannot_be_decrypted_by_current_keyring(tmp_path: Path):
    repo, db = _build_repo(tmp_path)
    key_a = _new_key()
    key_b = _new_key()
    try:
        guard = _build_guard(repository=repo, key_material=key_a)
        guard.ensure_ready()
    finally:
        db.close()

    repo2, db2 = _build_repo(tmp_path)
    try:
        guard = _build_guard(repository=repo2, key_material=key_b)

        with pytest.raises(VaultStartupKeyValidationError) as exc_info:
            guard.ensure_ready()

        assert exc_info.value.code == "VAULT_STARTUP_KEY_VALIDATION_ERROR"
        details_text = str(exc_info.value.details)
        assert key_a not in details_text
        assert key_b not in details_text
    finally:
        db2.close()


def test_startup_guard_fails_on_readonly_storage_even_when_probe_is_valid(tmp_path: Path):
    repo, db = _build_repo(tmp_path)
    key = _new_key()
    try:
        writable_guard = _build_guard(repository=repo, key_material=key)
        writable_guard.ensure_ready()

        readonly_guard = _build_guard(repository=_ReadonlyRepository(repo), key_material=key)

        with pytest.raises(VaultStartupStorageReadonlyError) as exc_info:
            readonly_guard.ensure_ready()

        assert exc_info.value.code == "VAULT_STARTUP_STORAGE_READONLY"
        assert exc_info.value.details["reason"] == "readonly_storage"
    finally:
        db.close()

