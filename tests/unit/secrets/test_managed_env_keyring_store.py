from __future__ import annotations

import fcntl
import multiprocessing
import os
import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from connector.domain.ports.secrets.key_provider import VaultMasterKey
from connector.domain.secrets.errors import SecretKeyConfigError
from connector.infra.secrets.management.managed_env_keyring_store import VaultManagedEnvKeyringStore


def _random_fernet_key() -> str:
    return Fernet.generate_key().decode("utf-8")


def _try_lock_nonblocking(lock_path: str, queue: multiprocessing.Queue[str]) -> None:
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            queue.put("acquired")
        except BlockingIOError:
            queue.put("blocked")
    finally:
        os.close(fd)


def test_save_and_load_roundtrip_with_permissions(tmp_path: Path) -> None:
    env_file = tmp_path / "cache" / "vault.env"
    store = VaultManagedEnvKeyringStore(str(env_file))
    keys = (
        VaultMasterKey(key_version="mk_2026", key_material=_random_fernet_key(), is_active=True),
        VaultMasterKey(key_version="mk_2025", key_material=_random_fernet_key(), is_active=False),
    )

    store.save_keyring(keys)
    loaded = store.load_keyring()

    assert [item.key_version for item in loaded] == ["mk_2026", "mk_2025"]
    assert loaded[0].is_active is True
    assert loaded[1].is_active is False
    assert stat.S_IMODE(env_file.stat().st_mode) == 0o600
    assert list(env_file.parent.glob(".ankey_vault_keyring_*.tmp")) == []


def test_load_supports_export_and_quoted_value(tmp_path: Path) -> None:
    env_file = tmp_path / "vault.env"
    keyring = f"mk_2026:{_random_fernet_key()},mk_2025:{_random_fernet_key()}"
    env_file.write_text(f'export ANKEY_VAULT_MASTER_KEYS="{keyring}"\n', encoding="utf-8")

    store = VaultManagedEnvKeyringStore(str(env_file))
    loaded = store.load_keyring()

    assert len(loaded) == 2
    assert loaded[0].key_version == "mk_2026"


def test_load_missing_file_maps_to_secret_key_config_error(tmp_path: Path) -> None:
    store = VaultManagedEnvKeyringStore(str(tmp_path / "missing.env"))

    with pytest.raises(SecretKeyConfigError) as exc_info:
        store.load_keyring()

    assert exc_info.value.code == "VAULT_STARTUP_KEY_CONFIG_ERROR"
    assert exc_info.value.details["reason"] == "managed_env_file_missing"


def test_load_missing_env_var_maps_to_secret_key_config_error(tmp_path: Path) -> None:
    env_file = tmp_path / "vault.env"
    env_file.write_text("OTHER_VAR=value\n", encoding="utf-8")
    store = VaultManagedEnvKeyringStore(str(env_file))

    with pytest.raises(SecretKeyConfigError) as exc_info:
        store.load_keyring()

    assert exc_info.value.code == "VAULT_STARTUP_KEY_CONFIG_ERROR"
    assert exc_info.value.details["reason"] == "managed_env_var_missing"


def test_lifecycle_lock_blocks_other_process(tmp_path: Path) -> None:
    env_file = tmp_path / "vault.env"
    store = VaultManagedEnvKeyringStore(str(env_file))
    queue: multiprocessing.Queue[str] = multiprocessing.Queue()

    with store.lifecycle_lock():
        process = multiprocessing.Process(
            target=_try_lock_nonblocking,
            args=(str(store.lock_path), queue),
        )
        process.start()
        process.join(timeout=5)
        assert process.exitcode == 0
        assert queue.get(timeout=1) == "blocked"

