"""
Назначение:
    Unseal-runtime реализация master wrapping key для vault.

Граница ответственности:
    - Выводит runtime master key из passphrase через Argon2id.
    - Проверяет passphrase через HMAC metadata без хранения master key на диске.
    - Предоставляет in-memory VaultKeyProviderPort для существующих vault сервисов.
    - Не запрашивает passphrase у пользователя и не знает о CLI/ENV.
"""

from __future__ import annotations

import base64
import hmac
import os
from dataclasses import replace
from hashlib import sha256

from argon2.low_level import Type, hash_secret_raw

from connector.domain.ports.secrets.key_provider import VaultKeyProviderPort, VaultMasterKey
from connector.domain.ports.secrets.repository import SecretVaultRepositoryPort
from connector.domain.secrets.errors import SecretKeyConfigError
from connector.domain.secrets.models import VaultUnsealMetadata

KDF_ARGON2ID = "argon2id"
HMAC_SHA256 = "hmac-sha256"
DEFAULT_UNSEAL_TIME_COST = 3
DEFAULT_UNSEAL_MEMORY_COST_KIB = 65536
DEFAULT_UNSEAL_PARALLELISM = 4
DEFAULT_UNSEAL_HASH_LEN = 32
DEFAULT_UNSEAL_SALT_LEN = 32
_HMAC_MESSAGE_PREFIX = b"ankey-vault-unseal-v1"


class VaultUnsealService:
    """
    Назначение:
        Чистый crypto-сервис unseal-модели.

    Контракт:
        `create_metadata()` генерирует salt/HMAC metadata и возвращает runtime key.
        `derive_key()` проверяет metadata и возвращает тот же runtime key для той же passphrase.
    """

    def create_metadata(
        self,
        *,
        passphrase: str,
        key_version: str,
        now_utc: str,
    ) -> tuple[VaultUnsealMetadata, VaultMasterKey]:
        self._require_passphrase(passphrase)
        metadata = VaultUnsealMetadata(
            key_version=key_version,
            kdf_algo=KDF_ARGON2ID,
            kdf_salt=os.urandom(DEFAULT_UNSEAL_SALT_LEN),
            kdf_time_cost=DEFAULT_UNSEAL_TIME_COST,
            kdf_memory_cost_kib=DEFAULT_UNSEAL_MEMORY_COST_KIB,
            kdf_parallelism=DEFAULT_UNSEAL_PARALLELISM,
            kdf_hash_len=DEFAULT_UNSEAL_HASH_LEN,
            hmac_algo=HMAC_SHA256,
            hmac_salt=os.urandom(DEFAULT_UNSEAL_SALT_LEN),
            hmac_digest=b"",
            created_at=now_utc,
            updated_at=now_utc,
        )
        raw_key = self._derive_raw_key(passphrase=passphrase, metadata=metadata)
        digest = self._build_hmac(raw_key=raw_key, metadata=metadata)
        metadata = replace(metadata, hmac_digest=digest)
        return metadata, self._to_master_key(key_version=key_version, raw_key=raw_key)

    def derive_key(self, *, passphrase: str, metadata: VaultUnsealMetadata) -> VaultMasterKey:
        self._require_passphrase(passphrase)
        raw_key = self._derive_raw_key(passphrase=passphrase, metadata=metadata)
        expected = self._build_hmac(raw_key=raw_key, metadata=metadata)
        if not hmac.compare_digest(expected, _bytes(metadata.hmac_digest)):
            raise SecretKeyConfigError(
                "Vault unseal passphrase is invalid",
                details={"reason": "unseal_passphrase_invalid"},
            )
        return self._to_master_key(key_version=metadata.key_version, raw_key=raw_key)

    def _derive_raw_key(self, *, passphrase: str, metadata: VaultUnsealMetadata) -> bytes:
        if metadata.kdf_algo != KDF_ARGON2ID:
            raise SecretKeyConfigError(
                "Unsupported vault unseal KDF",
                details={"reason": "unsupported_unseal_kdf", "kdf_algo": metadata.kdf_algo},
            )
        if metadata.kdf_hash_len != DEFAULT_UNSEAL_HASH_LEN:
            raise SecretKeyConfigError(
                "Unsupported vault unseal key length",
                details={"reason": "unsupported_unseal_key_length", "kdf_hash_len": metadata.kdf_hash_len},
            )
        try:
            return hash_secret_raw(
                secret=passphrase.encode("utf-8"),
                salt=_bytes(metadata.kdf_salt),
                time_cost=metadata.kdf_time_cost,
                memory_cost=metadata.kdf_memory_cost_kib,
                parallelism=metadata.kdf_parallelism,
                hash_len=metadata.kdf_hash_len,
                type=Type.ID,
            )
        except Exception as exc:  # noqa: BLE001
            raise SecretKeyConfigError(
                "Failed to derive vault unseal key",
                details={"reason": "unseal_kdf_failed", "error_type": type(exc).__name__},
            ) from exc

    def _build_hmac(self, *, raw_key: bytes, metadata: VaultUnsealMetadata) -> bytes:
        if metadata.hmac_algo != HMAC_SHA256:
            raise SecretKeyConfigError(
                "Unsupported vault unseal HMAC",
                details={"reason": "unsupported_unseal_hmac", "hmac_algo": metadata.hmac_algo},
            )
        message = _HMAC_MESSAGE_PREFIX + b"|" + _bytes(metadata.hmac_salt)
        return hmac.new(raw_key, message, sha256).digest()

    def _to_master_key(self, *, key_version: str, raw_key: bytes) -> VaultMasterKey:
        return VaultMasterKey(
            key_version=key_version,
            key_material=base64.urlsafe_b64encode(raw_key).decode("ascii"),
            is_active=True,
        )

    def _require_passphrase(self, passphrase: str) -> None:
        if passphrase == "":
            raise SecretKeyConfigError(
                "Vault unseal passphrase is empty",
                details={"reason": "unseal_passphrase_empty"},
            )


class UnsealedVaultKeyProvider(VaultKeyProviderPort):
    """
    Назначение:
        Lazy in-memory key provider для runtime vault-сервисов.
    """

    def __init__(
        self,
        *,
        repository: SecretVaultRepositoryPort,
        unseal_service: VaultUnsealService,
        passphrase: str | None,
    ) -> None:
        self._repository = repository
        self._unseal_service = unseal_service
        self._passphrase = passphrase
        self._active_key: VaultMasterKey | None = None

    def get_active_key(self) -> VaultMasterKey:
        if self._active_key is None:
            self._active_key = self._load_active_key()
        return self._active_key

    def get_all_keys(self) -> tuple[VaultMasterKey, ...]:
        return (self.get_active_key(),)

    def find_key(self, key_version: str) -> VaultMasterKey | None:
        active = self.get_active_key()
        if active.key_version == key_version:
            return active
        return None

    def _load_active_key(self) -> VaultMasterKey:
        if self._passphrase is None:
            raise SecretKeyConfigError(
                "Vault unseal passphrase was not provided",
                details={"reason": "unseal_passphrase_missing"},
            )
        metadata = self._repository.get_unseal_metadata()
        if metadata is None:
            raise SecretKeyConfigError(
                "Vault unseal metadata is missing",
                details={"reason": "unseal_metadata_missing"},
            )
        return self._unseal_service.derive_key(passphrase=self._passphrase, metadata=metadata)


def _bytes(value: bytes | str) -> bytes:
    if isinstance(value, bytes):
        return value
    return value.encode("utf-8")


__all__ = [
    "VaultUnsealService",
    "UnsealedVaultKeyProvider",
    "KDF_ARGON2ID",
    "HMAC_SHA256",
]
