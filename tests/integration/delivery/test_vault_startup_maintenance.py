from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from connector.config.models import AppConfig
from connector.config.projections import to_vault_db_config
from connector.delivery.cli import containers as containers_module
from connector.delivery.cli.containers import vault_startup_resource
from connector.domain.ports.secrets.key_provider import VaultMasterKey
from connector.domain.secrets.vault_startup_guard import VaultStartupGuard
from connector.infra.secrets.env_key_provider import DEFAULT_MASTER_KEYS_ENV
from connector.infra.secrets.fernet_envelope_cipher import FernetEnvelopeCipher
from connector.infra.secrets.management.managed_env_keyring_store import VaultManagedEnvKeyringStore
from connector.infra.secrets.sqlite.repository import SqliteVaultRepository
from connector.infra.sqlite.engine import SqliteEngine, open_sqlite


def _provider_from_keyring(keys: tuple[VaultMasterKey, ...]):
    class _KeyProvider:
        def __init__(self, keyring: tuple[VaultMasterKey, ...]) -> None:
            self._keys = keyring
            self._active = keyring[0]
            self._by_version = {item.key_version: item for item in keyring}

        def get_active_key(self) -> VaultMasterKey:
            return self._active

        def get_all_keys(self) -> tuple[VaultMasterKey, ...]:
            return self._keys

        def find_key(self, key_version: str) -> VaultMasterKey | None:
            return self._by_version.get(key_version)

    return _KeyProvider(keys)


def _build_engine(tmp_path: Path) -> SqliteEngine:
    return open_sqlite(
        to_vault_db_config(AppConfig()),
        str(tmp_path / "cache" / "ankey_vault.sqlite3"),
    )


def _management_app_config(
    *,
    tmp_path: Path,
    managed_env_file: str,
    auto_rotate_enabled: bool,
    auto_rotate_on_error: str = "fail_closed",
    interval_days: int = 30,
) -> AppConfig:
    return AppConfig.model_validate(
        {
            "paths": {"cache_dir": str(tmp_path / "cache")},
            "vault_management": {
                "managed_env_file": managed_env_file,
                "auto_rotate_enabled": auto_rotate_enabled,
                "auto_rotate_interval": {"days": interval_days},
                "auto_rotate_on_error": auto_rotate_on_error,
            },
        }
    )


def _bootstrap_probe(repo: SqliteVaultRepository, engine: SqliteEngine, key: VaultMasterKey) -> None:
    guard = VaultStartupGuard(
        repository=repo,
        cipher=FernetEnvelopeCipher(),
        key_provider=_provider_from_keyring((key,)),
        storage_probe=engine,
    )
    guard.ensure_ready()


def test_startup_maintenance_noop_when_not_due(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(DEFAULT_MASTER_KEYS_ENV, raising=False)
    engine = _build_engine(tmp_path)
    try:
        repo = SqliteVaultRepository(engine)
        old_key = VaultMasterKey(
            key_version="mk_old",
            key_material=Fernet.generate_key().decode("utf-8"),
            is_active=True,
        )
        _bootstrap_probe(repo, engine, old_key)
        repo.set_last_rotated_at("2026-03-05T00:00:00+00:00")

        store = VaultManagedEnvKeyringStore(str(tmp_path / "cache" / "vault.env"))
        store.save_keyring((old_key,))

        app_config = _management_app_config(
            tmp_path=tmp_path,
            managed_env_file=str(tmp_path / "cache" / "vault.env"),
            auto_rotate_enabled=True,
        )
        resource = vault_startup_resource(engine=engine, app_config=app_config)
        next(resource)
        try:
            loaded = store.load_keyring()
            assert [item.key_version for item in loaded] == ["mk_old"]
        finally:
            resource.close()
    finally:
        engine.close()


def test_startup_maintenance_finalizes_inflight_bridge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(DEFAULT_MASTER_KEYS_ENV, raising=False)
    engine = _build_engine(tmp_path)
    try:
        repo = SqliteVaultRepository(engine)
        old_key = VaultMasterKey(
            key_version="mk_old",
            key_material=Fernet.generate_key().decode("utf-8"),
            is_active=True,
        )
        new_key = VaultMasterKey(
            key_version="mk_new",
            key_material=Fernet.generate_key().decode("utf-8"),
            is_active=True,
        )
        _bootstrap_probe(repo, engine, old_key)

        store = VaultManagedEnvKeyringStore(str(tmp_path / "cache" / "vault.env"))
        store.save_keyring((new_key, old_key))

        app_config = _management_app_config(
            tmp_path=tmp_path,
            managed_env_file=str(tmp_path / "cache" / "vault.env"),
            auto_rotate_enabled=True,
        )
        resource = vault_startup_resource(engine=engine, app_config=app_config)
        next(resource)
        try:
            loaded = store.load_keyring()
            assert [item.key_version for item in loaded] == ["mk_new"]
            assert all(item.wrap_key_version == "mk_new" for item in repo.list_deks())
            assert repo.get_last_rotation_reason() == "bridge_finalize_completed"
        finally:
            resource.close()
    finally:
        engine.close()


def test_startup_maintenance_fail_open_continues_on_maintenance_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(DEFAULT_MASTER_KEYS_ENV, raising=False)
    engine = _build_engine(tmp_path)
    try:
        repo = SqliteVaultRepository(engine)
        key = VaultMasterKey(
            key_version="mk_old",
            key_material=Fernet.generate_key().decode("utf-8"),
            is_active=True,
        )
        _bootstrap_probe(repo, engine, key)
        store = VaultManagedEnvKeyringStore(str(tmp_path / "cache" / "vault.env"))
        store.save_keyring((key,))

        class _FailingMaintenance:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                _ = (args, kwargs)

            def run_if_due(self):
                raise RuntimeError("maintenance_failed")

        monkeypatch.setattr(containers_module, "VaultMaintenanceUseCase", _FailingMaintenance)

        app_config = _management_app_config(
            tmp_path=tmp_path,
            managed_env_file=str(tmp_path / "cache" / "vault.env"),
            auto_rotate_enabled=True,
            auto_rotate_on_error="fail_open",
        )
        resource = vault_startup_resource(engine=engine, app_config=app_config)
        next(resource)
        resource.close()
    finally:
        engine.close()


def test_startup_maintenance_fail_closed_raises_on_maintenance_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv(DEFAULT_MASTER_KEYS_ENV, raising=False)
    engine = _build_engine(tmp_path)
    try:
        repo = SqliteVaultRepository(engine)
        key = VaultMasterKey(
            key_version="mk_old",
            key_material=Fernet.generate_key().decode("utf-8"),
            is_active=True,
        )
        _bootstrap_probe(repo, engine, key)
        store = VaultManagedEnvKeyringStore(str(tmp_path / "cache" / "vault.env"))
        store.save_keyring((key,))

        class _FailingMaintenance:
            def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
                _ = (args, kwargs)

            def run_if_due(self):
                raise RuntimeError("maintenance_failed")

        monkeypatch.setattr(containers_module, "VaultMaintenanceUseCase", _FailingMaintenance)

        app_config = _management_app_config(
            tmp_path=tmp_path,
            managed_env_file=str(tmp_path / "cache" / "vault.env"),
            auto_rotate_enabled=True,
            auto_rotate_on_error="fail_closed",
        )
        resource = vault_startup_resource(engine=engine, app_config=app_config)
        with pytest.raises(RuntimeError, match="maintenance_failed"):
            next(resource)
        resource.close()
    finally:
        engine.close()
