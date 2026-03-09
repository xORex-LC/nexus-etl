from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

from connector.config.models import AppConfig
from connector.config.projections import to_vault_db_config
from connector.domain.ports.secrets.key_provider import VaultMasterKey
from connector.domain.secrets.errors import SecretDecryptionError
from connector.domain.secrets.models import VaultDekRecord
from connector.domain.secrets.vault_startup_guard import VaultStartupGuard
from connector.infra.secrets.fernet_envelope_cipher import FERNET_V1, FernetEnvelopeCipher
from connector.infra.secrets.management.managed_env_keyring_store import VaultManagedEnvKeyringStore
from connector.infra.secrets.sqlite.repository import SqliteVaultRepository
from connector.infra.sqlite.engine import SqliteEngine, open_sqlite
from connector.usecases.management.vault import (
    VaultKeyManagementUseCase,
    VaultStartupGuardPostVerifier,
)


def _serialize_keyring(keys: tuple[VaultMasterKey, ...]) -> str:
    return ",".join(f"{item.key_version}:{item.key_material}" for item in keys)


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


def test_rotate_and_rewrap_reaches_single_key_steady_state(tmp_path: Path) -> None:
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
        store.save_keyring((old_key,))

        startup_guard = VaultStartupGuard(
            repository=repo,
            cipher=cipher,
            key_provider=_provider_from_keyring((old_key,)),
            storage_probe=engine,
        )
        startup_guard.ensure_ready()

        extra_dek_plain = Fernet.generate_key()
        extra_wrapped = cipher.wrap_dek(
            dek_plaintext=extra_dek_plain,
            master_key=old_key.key_material,
            wrap_algo=FERNET_V1,
        )
        repo.upsert_dek(
            VaultDekRecord(
                dek_version="dek_extra",
                wrapped_dek=extra_wrapped,
                wrap_algo=FERNET_V1,
                wrap_key_version="mk_old",
                is_active=False,
                created_at="2026-03-04T00:00:00+00:00",
                updated_at="2026-03-04T00:00:00+00:00",
            )
        )

        usecase = VaultKeyManagementUseCase(
            repository=repo,
            cipher=cipher,
            keyring_store=store,
            post_verify=VaultStartupGuardPostVerifier(
                repository=repo,
                cipher=cipher,
                storage_probe=engine,
            ),
            now_utc=lambda: "2026-03-04T10:00:00+00:00",
            run_id_factory=lambda: "run-rotate-int-001",
            key_version_factory=lambda: "mk_new",
            key_material_factory=lambda: Fernet.generate_key().decode("utf-8"),
        )

        result = usecase.rotate_and_rewrap()

        assert result.operation == "rotate"
        assert result.run_id == "run-rotate-int-001"
        assert result.active_key_version == "mk_new"
        assert result.final_key_count == 1

        final_keyring = store.load_keyring()
        assert [item.key_version for item in final_keyring] == ["mk_new"]

        all_deks = repo.list_deks()
        assert len(all_deks) >= 2
        assert all(item.wrap_key_version == "mk_new" for item in all_deks)

        assert repo.get_last_rotation_result() == "ok"
        assert repo.get_last_rotation_reason() == "rotate_completed"
        assert repo.get_last_rotation_run_id() == "run-rotate-int-001"
        assert repo.get_last_rotated_at() == "2026-03-04T10:00:00+00:00"

        with_key_old = old_key.key_material
        for dek_record in all_deks:
            try:
                cipher.unwrap_dek(
                    wrapped_dek=dek_record.wrapped_dek,
                    master_key=with_key_old,
                    wrap_algo=FERNET_V1,
                )
            except SecretDecryptionError:
                continue
            raise AssertionError("DEK was not rewrapped to new key")
    finally:
        engine.close()
