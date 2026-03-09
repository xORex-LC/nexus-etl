from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

from connector.config.models import AppConfig
from connector.config.projections import to_vault_db_config
from connector.domain.ports.secrets.key_provider import VaultMasterKey
from connector.domain.secrets.models import VaultDekRecord
from connector.domain.secrets.policy.rotation_policy import VaultRotationInterval, VaultRotationPolicy
from connector.domain.secrets.vault_startup_guard import VaultStartupGuard
from connector.infra.secrets.fernet_envelope_cipher import FERNET_V1, FernetEnvelopeCipher
from connector.infra.secrets.management.managed_env_keyring_store import VaultManagedEnvKeyringStore
from connector.infra.secrets.sqlite.repository import SqliteVaultRepository
from connector.infra.sqlite.engine import SqliteEngine, open_sqlite
from connector.usecases.management.vault import (
    VaultKeyManagementUseCase,
    VaultMaintenanceUseCase,
    VaultStartupGuardPostVerifier,
)


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


def _build_usecase(
    *,
    engine: SqliteEngine,
    store: VaultManagedEnvKeyringStore,
    run_id: str,
) -> tuple[SqliteVaultRepository, FernetEnvelopeCipher, VaultKeyManagementUseCase]:
    repo = SqliteVaultRepository(engine)
    cipher = FernetEnvelopeCipher()
    usecase = VaultKeyManagementUseCase(
        repository=repo,
        cipher=cipher,
        keyring_store=store,
        post_verify=VaultStartupGuardPostVerifier(
            repository=repo,
            cipher=cipher,
            storage_probe=engine,
        ),
        run_id_factory=lambda: run_id,
    )
    return repo, cipher, usecase


def test_usecase_lifecycle_init_rotate_rewrap_delete_key(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    try:
        store = VaultManagedEnvKeyringStore(str(tmp_path / "cache" / "vault.env"))
        _, _, usecase = _build_usecase(engine=engine, store=store, run_id="run-lifecycle-int-001")

        init_result = usecase.init_keyring()
        assert init_result.operation == "init"

        rotated = usecase.rotate_and_rewrap()
        assert rotated.operation == "rotate"
        assert rotated.active_key_version != init_result.active_key_version

        rewrapped = usecase.rewrap_all_dek()
        assert rewrapped.operation == "rewrap"
        assert rewrapped.active_key_version == rotated.active_key_version

        deleted = usecase.delete_key()
        assert deleted.operation == "delete_key"
        assert deleted.active_key_version != rotated.active_key_version

        status = usecase.status()
        assert status.active_key_version == deleted.active_key_version
        assert status.bridge_keyring is False
        assert len(status.key_versions) == 1
    finally:
        engine.close()


def test_run_maintenance_rotates_when_due_and_noop_when_not_due(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    try:
        store = VaultManagedEnvKeyringStore(str(tmp_path / "cache" / "vault.env"))
        repo, _, usecase = _build_usecase(engine=engine, store=store, run_id="run-maintenance-int-001")

        initial = usecase.init_keyring()
        repo.set_last_rotated_at("2020-01-01T00:00:00+00:00")

        rotate_maintenance = VaultMaintenanceUseCase(
            key_management=usecase,
            rotation_policy=VaultRotationPolicy(interval=VaultRotationInterval(days=30)),
            now_utc=lambda: "2026-03-06T00:00:00+00:00",
            run_id_factory=lambda: "run-maintenance-int-rotate",
        )
        rotated = rotate_maintenance.run_if_due()
        assert rotated.action == "rotate"
        assert rotated.changed is True
        assert rotated.active_key_version is not None
        assert rotated.active_key_version != initial.active_key_version

        repo.set_last_rotated_at("2026-03-06T00:00:00+00:00")
        noop_maintenance = VaultMaintenanceUseCase(
            key_management=usecase,
            rotation_policy=VaultRotationPolicy(interval=VaultRotationInterval(days=30)),
            now_utc=lambda: "2026-03-06T00:00:00+00:00",
            run_id_factory=lambda: "run-maintenance-int-noop",
        )
        no_op = noop_maintenance.run_if_due()
        assert no_op.action == "no_op"
        assert no_op.changed is False
    finally:
        engine.close()


def test_interrupted_rotate_bridge_is_finalized_by_maintenance(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    try:
        repo = SqliteVaultRepository(engine)
        cipher = FernetEnvelopeCipher()
        store = VaultManagedEnvKeyringStore(str(tmp_path / "cache" / "vault.env"))

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
        store.save_keyring((old_key,))

        startup_guard = VaultStartupGuard(
            repository=repo,
            cipher=cipher,
            key_provider=_provider_from_keyring((old_key,)),
            storage_probe=engine,
        )
        startup_guard.ensure_ready()

        extra_plain = Fernet.generate_key()
        extra_wrapped = cipher.wrap_dek(
            dek_plaintext=extra_plain,
            master_key=old_key.key_material,
            wrap_algo=FERNET_V1,
        )
        repo.upsert_dek(
            VaultDekRecord(
                dek_version="dek_extra",
                wrapped_dek=extra_wrapped,
                wrap_algo=FERNET_V1,
                wrap_key_version=old_key.key_version,
                is_active=False,
                created_at="2026-03-01T00:00:00+00:00",
                updated_at="2026-03-01T00:00:00+00:00",
            )
        )

        # Эмуляция crash-safe in-flight состояния после падения rotate:
        # keyring в bridge-режиме, часть DEK ещё на старом ключе.
        store.save_keyring((new_key, old_key))
        usecase = VaultKeyManagementUseCase(
            repository=repo,
            cipher=cipher,
            keyring_store=store,
            post_verify=VaultStartupGuardPostVerifier(
                repository=repo,
                cipher=cipher,
                storage_probe=engine,
            ),
            run_id_factory=lambda: "run-maintenance-int-finalize",
        )
        maintenance = VaultMaintenanceUseCase(
            key_management=usecase,
            rotation_policy=VaultRotationPolicy(interval=VaultRotationInterval(days=30)),
            run_id_factory=lambda: "run-maintenance-int-finalize",
        )

        result = maintenance.run_if_due()

        assert result.action == "bridge_finalize"
        assert result.changed is True
        assert result.active_key_version == "mk_new"

        keyring = store.load_keyring()
        assert len(keyring) == 1
        assert keyring[0].key_version == "mk_new"
        all_deks = repo.list_deks()
        assert all(item.wrap_key_version == "mk_new" for item in all_deks)
    finally:
        engine.close()


def test_init_accepts_imported_initial_keyring(tmp_path: Path) -> None:
    engine = _build_engine(tmp_path)
    try:
        store = VaultManagedEnvKeyringStore(str(tmp_path / "cache" / "vault.env"))
        _, _, usecase = _build_usecase(engine=engine, store=store, run_id="run-import-int-001")
        imported_key = VaultMasterKey(
            key_version="mk_imported",
            key_material=Fernet.generate_key().decode("utf-8"),
            is_active=False,
        )

        result = usecase.init_keyring(initial_keyring=(imported_key,))

        assert result.operation == "init"
        assert result.active_key_version == "mk_imported"
        keyring = store.load_keyring()
        assert len(keyring) == 1
        assert keyring[0].key_version == "mk_imported"
        assert keyring[0].is_active is True
    finally:
        engine.close()

