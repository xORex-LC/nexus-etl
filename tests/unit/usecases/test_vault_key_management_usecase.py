from __future__ import annotations

from contextlib import contextmanager

import pytest
from cryptography.fernet import Fernet

from connector.domain.ports.secrets.key_provider import VaultMasterKey
from connector.domain.secrets.errors import SecretKeyConfigError, VaultManagementOperationError
from connector.domain.secrets.models import VaultDekRecord
from connector.infra.secrets.fernet_envelope_cipher import FERNET_V1, FernetEnvelopeCipher
from connector.usecases.management.vault import VaultKeyManagementUseCase


def _key(version: str, *, active: bool = False) -> VaultMasterKey:
    return VaultMasterKey(
        key_version=version,
        key_material=Fernet.generate_key().decode("utf-8"),
        is_active=active,
    )


def _build_wrapped_dek(cipher: FernetEnvelopeCipher, master_key: str) -> tuple[bytes, bytes]:
    dek_plaintext = Fernet.generate_key()
    wrapped = cipher.wrap_dek(
        dek_plaintext=dek_plaintext,
        master_key=master_key,
        wrap_algo=FERNET_V1,
    )
    assert isinstance(wrapped, bytes)
    return dek_plaintext, wrapped


class _InMemoryVaultRepository:
    def __init__(self, *, deks: tuple[VaultDekRecord, ...] = ()) -> None:
        self._deks = {item.dek_version: item for item in deks}
        self._meta: dict[str, str] = {}

    @contextmanager
    def transaction(self):
        yield

    def upsert_dek(self, record: VaultDekRecord) -> None:
        self._deks[record.dek_version] = record

    def list_deks(self) -> tuple[VaultDekRecord, ...]:
        return tuple(self._deks.values())

    def set_last_rotated_at(self, iso_utc: str) -> None:
        self._meta["last_rotated_at"] = iso_utc

    def get_last_rotated_at(self) -> str | None:
        return self._meta.get("last_rotated_at")

    def set_last_rotation_result(self, *, result: str, reason: str | None = None) -> None:
        self._meta["last_rotation_result"] = result
        if reason is None:
            self._meta.pop("last_rotation_reason", None)
        else:
            self._meta["last_rotation_reason"] = reason

    def get_last_rotation_result(self) -> str | None:
        return self._meta.get("last_rotation_result")

    def get_last_rotation_reason(self) -> str | None:
        return self._meta.get("last_rotation_reason")

    def set_last_rotation_run_id(self, run_id: str | None) -> None:
        if run_id is None:
            self._meta.pop("last_rotation_run_id", None)
        else:
            self._meta["last_rotation_run_id"] = run_id

    def get_last_rotation_run_id(self) -> str | None:
        return self._meta.get("last_rotation_run_id")


class _FailingRewrapRepository(_InMemoryVaultRepository):
    def __init__(self, *, deks: tuple[VaultDekRecord, ...]) -> None:
        super().__init__(deks=deks)
        self._failed = False

    def upsert_dek(self, record: VaultDekRecord) -> None:
        if not self._failed:
            self._failed = True
            raise RuntimeError("simulated_upsert_failure")
        super().upsert_dek(record)


class _InMemoryKeyringStore:
    def __init__(self, keyring: tuple[VaultMasterKey, ...] | None = None) -> None:
        self._keyring = keyring
        self.save_history: list[tuple[VaultMasterKey, ...]] = []

    @contextmanager
    def lifecycle_lock(self):
        yield

    def load_keyring(self) -> tuple[VaultMasterKey, ...]:
        if self._keyring is None:
            raise SecretKeyConfigError(
                details={"reason": "managed_env_file_missing"},
            )
        return self._keyring

    def save_keyring(self, keys: tuple[VaultMasterKey, ...]) -> None:
        self._keyring = keys
        self.save_history.append(keys)


class _Verifier:
    def __init__(self) -> None:
        self.calls: list[tuple[VaultMasterKey, ...]] = []

    def ensure_ready(self, keyring: tuple[VaultMasterKey, ...]) -> None:
        self.calls.append(keyring)


def test_init_keyring_creates_first_key_and_updates_metadata() -> None:
    repo = _InMemoryVaultRepository()
    store = _InMemoryKeyringStore(keyring=None)
    verifier = _Verifier()
    usecase = VaultKeyManagementUseCase(
        repository=repo,
        cipher=FernetEnvelopeCipher(),
        keyring_store=store,
        post_verify=verifier,
        now_utc=lambda: "2026-03-04T00:00:00+00:00",
        run_id_factory=lambda: "run-init-001",
        key_version_factory=lambda: "mk_new",
        key_material_factory=lambda: Fernet.generate_key().decode("utf-8"),
    )

    result = usecase.init_keyring()

    assert result.operation == "init"
    assert result.run_id == "run-init-001"
    assert result.active_key_version == "mk_new"
    assert repo.get_last_rotation_result() == "ok"
    assert repo.get_last_rotation_reason() == "init_completed"
    assert repo.get_last_rotation_run_id() == "run-init-001"
    assert repo.get_last_rotated_at() == "2026-03-04T00:00:00+00:00"
    assert len(verifier.calls) == 1
    assert verifier.calls[0][0].key_version == "mk_new"


def test_init_keyring_rejects_already_initialized_state() -> None:
    existing = _key("mk_existing", active=True)
    usecase = VaultKeyManagementUseCase(
        repository=_InMemoryVaultRepository(),
        cipher=FernetEnvelopeCipher(),
        keyring_store=_InMemoryKeyringStore(keyring=(existing,)),
        post_verify=_Verifier(),
        run_id_factory=lambda: "run-init-002",
    )

    with pytest.raises(VaultManagementOperationError) as exc_info:
        usecase.init_keyring()

    assert exc_info.value.details["reason"] == "already_initialized"


def test_rotate_and_rewrap_persists_bridge_then_final_single_key() -> None:
    cipher = FernetEnvelopeCipher()
    old_key = _key("mk_old", active=True)
    dek_plaintext, wrapped = _build_wrapped_dek(cipher, old_key.key_material)
    repo = _InMemoryVaultRepository(
        deks=(
            VaultDekRecord(
                dek_version="dek_v1",
                wrapped_dek=wrapped,
                wrap_algo=FERNET_V1,
                wrap_key_version=old_key.key_version,
                is_active=True,
                created_at="2026-03-04T00:00:00+00:00",
                updated_at="2026-03-04T00:00:00+00:00",
            ),
        )
    )
    store = _InMemoryKeyringStore(keyring=(old_key,))
    verifier = _Verifier()
    new_key_material = Fernet.generate_key().decode("utf-8")
    usecase = VaultKeyManagementUseCase(
        repository=repo,
        cipher=cipher,
        keyring_store=store,
        post_verify=verifier,
        now_utc=lambda: "2026-03-04T00:10:00+00:00",
        run_id_factory=lambda: "run-rotate-001",
        key_version_factory=lambda: "mk_new",
        key_material_factory=lambda: new_key_material,
    )

    result = usecase.rotate_and_rewrap()

    assert result.operation == "rotate"
    assert result.active_key_version == "mk_new"
    assert result.final_key_count == 1
    assert len(store.save_history) == 2
    assert [item.key_version for item in store.save_history[0]] == ["mk_new", "mk_old"]
    assert [item.key_version for item in store.save_history[1]] == ["mk_new"]
    assert repo.get_last_rotation_result() == "ok"
    assert repo.get_last_rotation_reason() == "rotate_completed"
    assert repo.get_last_rotation_run_id() == "run-rotate-001"

    rewrapped = repo.list_deks()[0]
    assert rewrapped.wrap_key_version == "mk_new"
    # Санити-проверка: DEK теперь раскрывается новым ключом.
    assert (
        cipher.unwrap_dek(
            wrapped_dek=rewrapped.wrapped_dek,
            master_key=new_key_material,
            wrap_algo=FERNET_V1,
        )
        == dek_plaintext
    )


def test_rewrap_all_dek_updates_status_without_rotated_at_change() -> None:
    cipher = FernetEnvelopeCipher()
    active_key = _key("mk_active", active=True)
    _, wrapped = _build_wrapped_dek(cipher, active_key.key_material)
    repo = _InMemoryVaultRepository(
        deks=(
            VaultDekRecord(
                dek_version="dek_v1",
                wrapped_dek=wrapped,
                wrap_algo=FERNET_V1,
                wrap_key_version=active_key.key_version,
                is_active=True,
                created_at="2026-03-04T00:00:00+00:00",
                updated_at="2026-03-04T00:00:00+00:00",
            ),
        )
    )
    repo.set_last_rotated_at("2026-03-01T00:00:00+00:00")
    usecase = VaultKeyManagementUseCase(
        repository=repo,
        cipher=cipher,
        keyring_store=_InMemoryKeyringStore(keyring=(active_key,)),
        post_verify=_Verifier(),
        now_utc=lambda: "2026-03-04T00:20:00+00:00",
        run_id_factory=lambda: "run-rewrap-001",
    )

    result = usecase.rewrap_all_dek()

    assert result.operation == "rewrap"
    assert repo.get_last_rotation_result() == "ok"
    assert repo.get_last_rotation_reason() == "rewrap_completed"
    assert repo.get_last_rotation_run_id() == "run-rewrap-001"
    assert repo.get_last_rotated_at() == "2026-03-01T00:00:00+00:00"


def test_delete_key_executes_replace_flow() -> None:
    cipher = FernetEnvelopeCipher()
    old_key = _key("mk_old", active=True)
    _, wrapped = _build_wrapped_dek(cipher, old_key.key_material)
    repo = _InMemoryVaultRepository(
        deks=(
            VaultDekRecord(
                dek_version="dek_v1",
                wrapped_dek=wrapped,
                wrap_algo=FERNET_V1,
                wrap_key_version=old_key.key_version,
                is_active=True,
                created_at="2026-03-04T00:00:00+00:00",
                updated_at="2026-03-04T00:00:00+00:00",
            ),
        )
    )
    store = _InMemoryKeyringStore(keyring=(old_key,))
    usecase = VaultKeyManagementUseCase(
        repository=repo,
        cipher=cipher,
        keyring_store=store,
        post_verify=_Verifier(),
        now_utc=lambda: "2026-03-04T00:30:00+00:00",
        run_id_factory=lambda: "run-delete-001",
        key_version_factory=lambda: "mk_replace",
        key_material_factory=lambda: Fernet.generate_key().decode("utf-8"),
    )

    result = usecase.delete_key()

    assert result.operation == "delete_key"
    assert result.active_key_version == "mk_replace"
    assert [item.key_version for item in store.save_history[-1]] == ["mk_replace"]


def test_rotate_failure_keeps_bridge_keyring_as_recoverable_state() -> None:
    cipher = FernetEnvelopeCipher()
    old_key = _key("mk_old", active=True)
    _, wrapped = _build_wrapped_dek(cipher, old_key.key_material)
    repo = _FailingRewrapRepository(
        deks=(
            VaultDekRecord(
                dek_version="dek_v1",
                wrapped_dek=wrapped,
                wrap_algo=FERNET_V1,
                wrap_key_version=old_key.key_version,
                is_active=True,
                created_at="2026-03-04T00:00:00+00:00",
                updated_at="2026-03-04T00:00:00+00:00",
            ),
        )
    )
    store = _InMemoryKeyringStore(keyring=(old_key,))
    usecase = VaultKeyManagementUseCase(
        repository=repo,
        cipher=cipher,
        keyring_store=store,
        post_verify=_Verifier(),
        run_id_factory=lambda: "run-rotate-failed",
        key_version_factory=lambda: "mk_new",
        key_material_factory=lambda: Fernet.generate_key().decode("utf-8"),
    )

    with pytest.raises(VaultManagementOperationError):
        usecase.rotate_and_rewrap()

    assert len(store.save_history) == 1
    assert [item.key_version for item in store.save_history[0]] == ["mk_new", "mk_old"]
    assert repo.get_last_rotation_result() == "failed"
    assert repo.get_last_rotation_reason() == "rotate_failed"
    assert repo.get_last_rotation_run_id() == "run-rotate-failed"
