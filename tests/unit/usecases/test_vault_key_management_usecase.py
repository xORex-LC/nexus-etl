from __future__ import annotations

from contextlib import contextmanager

import pytest
from cryptography.fernet import Fernet

from connector.domain.ports.secrets.key_provider import VaultMasterKey
from connector.domain.secrets.errors import SecretKeyConfigError, VaultManagementOperationError
from connector.domain.secrets.models import VaultDekRecord, VaultUnsealMetadata
from connector.infra.secrets.fernet_envelope_cipher import FERNET_V1, FernetEnvelopeCipher
from connector.infra.secrets.unseal import VaultUnsealService
from connector.usecases.management.vault import VaultKeyManagementUseCase


class _Repo:
    def __init__(self, *, deks: tuple[VaultDekRecord, ...] = ()) -> None:
        self._deks = {item.dek_version: item for item in deks}
        self._meta: dict[str, str] = {}
        self.unseal_metadata: VaultUnsealMetadata | None = None

    @contextmanager
    def transaction(self):
        deks_snapshot = dict(self._deks)
        meta_snapshot = dict(self._meta)
        unseal_snapshot = self.unseal_metadata
        try:
            yield
        except Exception:
            self._deks = deks_snapshot
            self._meta = meta_snapshot
            self.unseal_metadata = unseal_snapshot
            raise

    def get_unseal_metadata(self) -> VaultUnsealMetadata | None:
        return self.unseal_metadata

    def upsert_unseal_metadata(self, metadata: VaultUnsealMetadata) -> None:
        self.unseal_metadata = metadata

    def list_deks(self) -> tuple[VaultDekRecord, ...]:
        return tuple(self._deks.values())

    def upsert_dek(self, record: VaultDekRecord) -> None:
        self._deks[record.dek_version] = record

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


class _Verifier:
    def __init__(self) -> None:
        self.calls: list[tuple[VaultMasterKey, ...]] = []

    def ensure_ready(self, keyring: tuple[VaultMasterKey, ...]) -> None:
        self.calls.append(keyring)


class _FailingVerifier:
    def ensure_ready(self, keyring: tuple[VaultMasterKey, ...]) -> None:
        _ = keyring
        raise RuntimeError("probe failed")


def _usecase(
    repo: _Repo,
    verifier: _Verifier | None = None,
    key_versions: tuple[str, ...] = ("mk_new",),
) -> VaultKeyManagementUseCase:
    versions = iter(key_versions)
    return VaultKeyManagementUseCase(
        repository=repo,
        cipher=FernetEnvelopeCipher(),
        unseal_service=VaultUnsealService(),
        post_verify=verifier or _Verifier(),
        now_utc=lambda: "2026-03-04T00:00:00+00:00",
        run_id_factory=lambda: "run-001",
        key_version_factory=lambda: next(versions),
    )


def _wrapped_dek(cipher: FernetEnvelopeCipher, key: str, key_version: str) -> tuple[bytes, VaultDekRecord]:
    plaintext = Fernet.generate_key()
    wrapped = cipher.wrap_dek(dek_plaintext=plaintext, master_key=key, wrap_algo=FERNET_V1)
    return plaintext, VaultDekRecord(
        dek_version="dek_v1",
        wrapped_dek=wrapped,
        wrap_algo=FERNET_V1,
        wrap_key_version=key_version,
        is_active=True,
        created_at="2026-03-04T00:00:00+00:00",
        updated_at="2026-03-04T00:00:00+00:00",
    )


def test_init_creates_unseal_metadata_and_verifies_probe() -> None:
    repo = _Repo()
    verifier = _Verifier()
    result = _usecase(repo, verifier).init_keyring(passphrase="correct horse battery")

    assert result.operation == "init"
    assert result.active_key_version == "mk_new"
    assert repo.unseal_metadata is not None
    assert repo.get_last_rotation_result() == "ok"
    assert repo.get_last_rotation_reason() == "init_completed"
    assert verifier.calls[0][0].key_version == "mk_new"


def test_init_rejects_existing_unseal_metadata() -> None:
    repo = _Repo()
    usecase = _usecase(repo, key_versions=("mk_old", "mk_rotated"))
    usecase.init_keyring(passphrase="correct horse battery")

    with pytest.raises(VaultManagementOperationError) as exc_info:
        usecase.init_keyring(passphrase="correct horse battery")

    assert exc_info.value.details["reason"] == "already_initialized"


def test_init_rolls_back_unseal_metadata_when_post_verify_fails() -> None:
    repo = _Repo()
    usecase = _usecase(repo, _FailingVerifier())

    with pytest.raises(VaultManagementOperationError) as exc_info:
        usecase.init_keyring(passphrase="correct horse battery")

    assert exc_info.value.details["reason"] == "init_failed"
    assert repo.unseal_metadata is None
    assert repo.get_last_rotation_result() == "failed"
    assert repo.get_last_rotation_reason() == "init_failed"


def test_rotate_with_wrong_old_passphrase_fails() -> None:
    repo = _Repo()
    usecase = _usecase(repo, key_versions=("mk_old", "mk_rotated"))
    usecase.init_keyring(passphrase="old passphrase")

    with pytest.raises(SecretKeyConfigError):
        usecase.rotate_and_rewrap(
            current_passphrase="wrong passphrase",
            new_passphrase="new passphrase",
        )


def test_rotate_rewraps_dek_and_updates_key_version() -> None:
    cipher = FernetEnvelopeCipher()
    repo = _Repo()
    usecase = _usecase(repo, key_versions=("mk_old", "mk_rotated"))
    usecase.init_keyring(passphrase="old passphrase")
    old_key = VaultUnsealService().derive_key(
        passphrase="old passphrase",
        metadata=repo.unseal_metadata,  # type: ignore[arg-type]
    )
    plaintext, record = _wrapped_dek(cipher, old_key.key_material, old_key.key_version)
    repo.upsert_dek(record)

    result = usecase.rotate_and_rewrap(
        current_passphrase="old passphrase",
        new_passphrase="new passphrase",
    )

    assert result.operation == "rotate"
    assert result.active_key_version != "mk_old"
    stored = repo.list_deks()[0]
    assert stored.wrap_key_version == result.active_key_version
    new_key = VaultUnsealService().derive_key(
        passphrase="new passphrase",
        metadata=repo.unseal_metadata,  # type: ignore[arg-type]
    )
    assert cipher.unwrap_dek(
        wrapped_dek=stored.wrapped_dek,
        master_key=new_key.key_material,
        wrap_algo=FERNET_V1,
    ) == plaintext


def test_rewrap_preserves_current_key_version() -> None:
    repo = _Repo()
    usecase = _usecase(repo)
    usecase.init_keyring(passphrase="current passphrase")
    active = repo.unseal_metadata.key_version  # type: ignore[union-attr]

    result = usecase.rewrap_all_dek(passphrase="current passphrase")

    assert result.operation == "rewrap"
    assert result.active_key_version == active
    assert repo.unseal_metadata.key_version == active  # type: ignore[union-attr]


def test_status_without_unseal_reports_initialized_state() -> None:
    repo = _Repo()
    usecase = _usecase(repo)
    assert usecase.status().initialized is False
    usecase.init_keyring(passphrase="current passphrase")

    status = usecase.status()

    assert status.initialized is True
    assert status.active_key_version == "mk_new"


def test_verify_unseal_runs_post_verify_probe() -> None:
    repo = _Repo()
    verifier = _Verifier()
    usecase = _usecase(repo, verifier)
    usecase.init_keyring(passphrase="current passphrase")

    active_key = usecase.verify_unseal(passphrase="current passphrase")

    assert active_key.key_version == "mk_new"
    assert len(verifier.calls) == 2
    assert verifier.calls[1][0].key_version == "mk_new"
