from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet
import pytest

from connector.config.app_settings import SqliteSettings, build_vault_db_config
from connector.domain.secrets.errors import (
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)
from connector.domain.secrets.vault_startup_guard import DEFAULT_PROBE_NAME, VaultStartupGuard
from connector.infra.secrets import EnvVaultKeyProvider, FernetEnvelopeCipher
from connector.infra.secrets.sqlite import SqliteVaultRepository
from connector.infra.sqlite.engine import open_sqlite, SqliteEngine


def _new_key() -> str:
    return Fernet.generate_key().decode("utf-8")


class _WritableStorageProbe:
    def is_readonly(self) -> bool:
        return False


class _ReadonlyStorageProbe:
    def is_readonly(self) -> bool:
        return True


def _build_repo(tmp_path: Path) -> tuple[SqliteEngine, SqliteVaultRepository]:
    engine = open_sqlite(
        build_vault_db_config(SqliteSettings()),
        str(tmp_path / "cache" / "ankey_vault.sqlite3"),
    )
    return engine, SqliteVaultRepository(engine)


def _build_guard(
    *,
    repository,
    key_material: str,
    key_version: str = "mk_2026",
    storage_probe=None,
) -> VaultStartupGuard:
    if storage_probe is None:
        storage_probe = _WritableStorageProbe()
    key_provider = EnvVaultKeyProvider(env={"ANKEY_VAULT_MASTER_KEYS": f"{key_version}:{key_material}"})
    return VaultStartupGuard(
        repository=repository,
        cipher=FernetEnvelopeCipher(),
        key_provider=key_provider,
        storage_probe=storage_probe,
    )


def test_startup_guard_creates_probe_when_absent_and_storage_writable(tmp_path: Path):
    engine, repo = _build_repo(tmp_path)
    try:
        guard = _build_guard(repository=repo, key_material=_new_key())

        guard.ensure_ready()

        stored_probe = repo.get_probe(probe_name=DEFAULT_PROBE_NAME)
        assert stored_probe is not None
        assert stored_probe.probe_name == DEFAULT_PROBE_NAME
        assert repo.get_active_dek() is not None
    finally:
        engine.close()


def test_startup_guard_fails_when_probe_absent_and_storage_readonly(tmp_path: Path):
    engine, repo = _build_repo(tmp_path)
    try:
        guard = _build_guard(
            repository=repo,
            key_material=_new_key(),
            storage_probe=_ReadonlyStorageProbe(),
        )

        with pytest.raises(VaultStartupUninitializedReadonlyError) as exc_info:
            guard.ensure_ready()

        assert exc_info.value.code == "VAULT_STARTUP_UNINITIALIZED_READONLY"
        assert exc_info.value.details["reason"] == "probe_missing"
    finally:
        engine.close()


def test_startup_guard_fails_on_corrupted_probe(tmp_path: Path):
    engine, repo = _build_repo(tmp_path)
    try:
        guard = _build_guard(repository=repo, key_material=_new_key())
        guard.ensure_ready()

        engine.execute(
            "UPDATE vault_probe SET ciphertext = ? WHERE probe_name = ?",
            (b"", DEFAULT_PROBE_NAME),
        )

        with pytest.raises(VaultStartupProbeCorruptedError) as exc_info:
            guard.ensure_ready()

        assert exc_info.value.code == "VAULT_STARTUP_PROBE_CORRUPTED"
        assert exc_info.value.details["reason"] == "probe_ciphertext_missing"
    finally:
        engine.close()


def test_startup_guard_fails_when_probe_cannot_be_decrypted_by_current_keyring(tmp_path: Path):
    key_a = _new_key()
    key_b = _new_key()

    engine_a, repo_a = _build_repo(tmp_path)
    try:
        guard = _build_guard(repository=repo_a, key_material=key_a)
        guard.ensure_ready()
    finally:
        engine_a.close()

    engine_b, repo_b = _build_repo(tmp_path)
    try:
        guard = _build_guard(repository=repo_b, key_material=key_b)

        with pytest.raises(VaultStartupKeyValidationError) as exc_info:
            guard.ensure_ready()

        assert exc_info.value.code == "VAULT_STARTUP_KEY_VALIDATION_ERROR"
        details_text = str(exc_info.value.details)
        assert key_a not in details_text
        assert key_b not in details_text
    finally:
        engine_b.close()


def test_startup_guard_fails_on_readonly_storage_even_when_probe_is_valid(tmp_path: Path):
    key = _new_key()
    engine, repo = _build_repo(tmp_path)
    try:
        writable_guard = _build_guard(repository=repo, key_material=key)
        writable_guard.ensure_ready()

        readonly_guard = _build_guard(
            repository=repo,
            key_material=key,
            storage_probe=_ReadonlyStorageProbe(),
        )

        with pytest.raises(VaultStartupStorageReadonlyError) as exc_info:
            readonly_guard.ensure_ready()

        assert exc_info.value.code == "VAULT_STARTUP_STORAGE_READONLY"
        assert exc_info.value.details["reason"] == "readonly_storage"
    finally:
        engine.close()


def test_startup_guard_calls_engine_is_readonly_not_transaction(tmp_path: Path):
    """Guard uses storage_probe.is_readonly(), не открывает транзакцию напрямую."""
    engine, repo = _build_repo(tmp_path)
    try:
        is_readonly_calls: list[bool] = []

        class _TrackedProbe:
            def is_readonly(self) -> bool:
                is_readonly_calls.append(True)
                return False

        guard = _build_guard(repository=repo, key_material=_new_key(), storage_probe=_TrackedProbe())
        guard.ensure_ready()

        assert len(is_readonly_calls) == 1, "storage_probe.is_readonly() должен быть вызван ровно один раз"
    finally:
        engine.close()
