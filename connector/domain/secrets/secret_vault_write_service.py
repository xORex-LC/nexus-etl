"""
Назначение:
    Write-path сервис Vault: `locator -> encrypt -> persist`.
"""

from __future__ import annotations

import base64
import os
from uuid import uuid4

from connector.common.time import get_utc_now_iso
from connector.domain.ports.secrets.cipher import SecretCipherPort
from connector.domain.ports.secrets.key_provider import VaultKeyProviderPort, VaultMasterKey
from connector.domain.ports.secrets.locator import SecretLocatorPort
from connector.domain.ports.secrets.provider import SecretStoreProtocol
from connector.domain.ports.secrets.repository import SecretVaultRepositoryPort
from connector.domain.secrets.errors import (
    SecretDecryptionError,
    SecretIntegrityError,
    SecretKeyConfigError,
    SecretReadError,
    SecretStoreError,
)
from connector.domain.secrets.models import VaultDekRecord, VaultSecretRecord

DEFAULT_LOCATOR_VERSION = "v1"
DEFAULT_CIPHER_ALGO = "FERNET_V1"
DEFAULT_WRAP_ALGO = "FERNET_V1"


class SecretVaultWriteService(SecretStoreProtocol):
    """
    Назначение:
        Реализация `SecretStoreProtocol` поверх vault repository и crypto-портов.

    Граница ответственности:
        - не знает о конкретном backend (SQLite/KMS);
        - не возвращает plaintext секретов наружу;
        - переводит сбои write-path в `SecretStoreError`.
    """

    def __init__(
        self,
        *,
        repository: SecretVaultRepositoryPort,
        cipher: SecretCipherPort,
        key_provider: VaultKeyProviderPort,
        locator: SecretLocatorPort,
        locator_version: str = DEFAULT_LOCATOR_VERSION,
        cipher_algo: str = DEFAULT_CIPHER_ALGO,
        wrap_algo: str = DEFAULT_WRAP_ALGO,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._key_provider = key_provider
        self._locator = locator
        self._locator_version = locator_version
        self._cipher_algo = cipher_algo
        self._wrap_algo = wrap_algo

    def put_many(
        self,
        *,
        dataset: str,
        match_key: str,
        secrets: dict[str, str],
        run_id: str | None = None,
    ) -> None:
        if not secrets:
            return
        normalized_match_key = match_key.strip()
        if not normalized_match_key:
            raise SecretStoreError(
                "Failed to store secrets in vault",
                details={"reason": "match_key_missing"},
            )

        now = get_utc_now_iso()
        source_ref = {"match_key": normalized_match_key}

        try:
            with self._repository.transaction():
                active_master_key = self._key_provider.get_active_key()
                dek_record, dek_plaintext = self._ensure_active_dek(active_master_key, now=now)

                for field, plaintext in secrets.items():
                    locator_hash = self._locator.build_locator_hash(
                        dataset=dataset,
                        field=field,
                        source_ref=source_ref,
                        locator_version=self._locator_version,
                    )
                    ciphertext = self._cipher.encrypt(
                        plaintext=plaintext,
                        dek_plaintext=dek_plaintext,
                        cipher_algo=self._cipher_algo,
                    )
                    self._repository.upsert_secret(
                        VaultSecretRecord(
                            dataset=dataset,
                            field=field,
                            match_key=normalized_match_key,
                            locator_hash=locator_hash,
                            locator_version=self._locator_version,
                            ciphertext=ciphertext,
                            cipher_algo=self._cipher_algo,
                            key_version=active_master_key.key_version,
                            dek_version=dek_record.dek_version,
                            run_id=run_id,
                            created_at=now,
                            updated_at=now,
                        )
                    )
        except SecretStoreError:
            raise
        except SecretReadError as exc:
            raise SecretStoreError(
                "Failed to store secrets in vault",
                details={"reason": "dek_read_failed"},
            ) from exc
        except (SecretKeyConfigError, SecretIntegrityError, SecretDecryptionError, ValueError) as exc:
            raise SecretStoreError(
                "Failed to store secrets in vault",
                details={"reason": "crypto_error"},
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise SecretStoreError(
                "Failed to store secrets in vault",
                details={"reason": "unexpected_error"},
            ) from exc

    def _ensure_active_dek(self, active_master_key: VaultMasterKey, *, now: str) -> tuple[VaultDekRecord, bytes]:
        active_dek = self._repository.get_active_dek()
        if active_dek is not None:
            return active_dek, self._unwrap_dek(active_dek)

        # Для Fernet-совместимого DEK нужен urlsafe base64 от 32 байт случайности.
        dek_plaintext = base64.urlsafe_b64encode(os.urandom(32))
        wrapped_dek = self._cipher.wrap_dek(
            dek_plaintext=dek_plaintext,
            master_key=active_master_key.key_material,
            wrap_algo=self._wrap_algo,
        )
        dek_record = VaultDekRecord(
            dek_version=_generate_dek_version(),
            wrapped_dek=wrapped_dek,
            wrap_algo=self._wrap_algo,
            wrap_key_version=active_master_key.key_version,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._repository.upsert_dek(dek_record)
        return dek_record, dek_plaintext

    def _unwrap_dek(self, record: VaultDekRecord) -> bytes:
        keys = self._candidate_master_keys(record.wrap_key_version)
        for key in keys:
            try:
                return self._cipher.unwrap_dek(
                    wrapped_dek=record.wrapped_dek,
                    master_key=key.key_material,
                    wrap_algo=record.wrap_algo,
                )
            except (SecretDecryptionError, SecretIntegrityError):
                continue

        raise SecretStoreError(
            "Failed to store secrets in vault",
            details={
                "reason": "dek_unwrap_failed",
                "dek_version": record.dek_version,
                "key_version": record.wrap_key_version,
            },
        )

    def _candidate_master_keys(self, wrap_key_version: str) -> list[VaultMasterKey]:
        candidates: list[VaultMasterKey] = []
        hinted = self._key_provider.find_key(wrap_key_version)
        if hinted is not None:
            candidates.append(hinted)
        for key in self._key_provider.get_all_keys():
            if hinted is not None and key.key_version == hinted.key_version:
                continue
            candidates.append(key)
        return candidates


def _generate_dek_version() -> str:
    return f"dek_{uuid4().hex}"
