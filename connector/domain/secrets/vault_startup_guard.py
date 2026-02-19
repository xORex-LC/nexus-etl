"""
Назначение:
    Startup fail-fast guard для vault runtime (`keyring + probe + storage readiness`).

Граница ответственности:
    - выполняет только startup-проверки и инициализацию probe при разрешённом сценарии;
    - не пишет пользовательские секреты и не участвует в apply/enrich обработке строк;
    - поднимает только `VAULT_STARTUP_*` ошибки для контролируемого отказа запуска.
"""

from __future__ import annotations

import base64
import os
from uuid import uuid4

from connector.common.time import getUtcNowIso
from connector.domain.ports.secrets.cipher import SecretCipherPort
from connector.domain.ports.secrets.key_provider import VaultKeyProviderPort, VaultMasterKey
from connector.domain.ports.secrets.repository import SecretVaultRepositoryPort
from connector.domain.secrets.errors import (
    SecretDecryptionError,
    SecretIntegrityError,
    SecretKeyConfigError,
    SecretReadError,
    SecretStoreError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)
from connector.domain.secrets.models import VaultDekRecord, VaultProbeRecord

DEFAULT_PROBE_NAME = "vault.system.healthcheck"
DEFAULT_PROBE_PAYLOAD = "vault_startup_probe_v1"
DEFAULT_CIPHER_ALGO = "FERNET_V1"
DEFAULT_WRAP_ALGO = "FERNET_V1"


class VaultStartupGuard:
    """
    Назначение:
        Проверить готовность vault до запуска pipeline/use-case.

    Инварианты:
        - startup policy v1 строгая: readonly storage блокирует запуск всегда;
        - `probe absent + writable` допускает auto-init probe;
        - plaintext probe и key material не попадают в ошибки/детали.
    """

    def __init__(
        self,
        *,
        repository: SecretVaultRepositoryPort,
        cipher: SecretCipherPort,
        key_provider: VaultKeyProviderPort,
        probe_name: str = DEFAULT_PROBE_NAME,
        probe_payload: str = DEFAULT_PROBE_PAYLOAD,
        cipher_algo: str = DEFAULT_CIPHER_ALGO,
        wrap_algo: str = DEFAULT_WRAP_ALGO,
        strict_readonly_policy: bool = True,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._key_provider = key_provider
        self._probe_name = probe_name
        self._probe_payload = probe_payload
        self._cipher_algo = cipher_algo
        self._wrap_algo = wrap_algo
        self._strict_readonly_policy = strict_readonly_policy

    def ensure_ready(self) -> None:
        """
        Назначение:
            Проверить startup readiness и бросить контролируемую ошибку при fail-fast ветках.

        Алгоритм:
            1. Проверить keyring и определить активный master key.
            2. Определить режим storage (writable/readonly) через write-capability probe.
            3. Прочитать probe; при отсутствии:
               - readonly -> `VAULT_STARTUP_UNINITIALIZED_READONLY`;
               - writable -> создать probe и сразу проверить decrypt.
            4. Провалидировать структуру probe и расшифровать её текущим keyring.
            5. В strict-policy v1 при readonly бросить `VAULT_STARTUP_STORAGE_READONLY`.
        """
        active_master_key = self._key_provider.get_active_key()
        readonly_storage = self._is_storage_readonly()

        probe = self._load_probe()
        if probe is None:
            if readonly_storage:
                raise VaultStartupUninitializedReadonlyError(
                    details={"reason": "probe_missing", "probe_name": self._probe_name},
                )
            probe = self._create_probe(active_master_key)

        self._validate_probe_record(probe)
        self._verify_probe(probe)

        if readonly_storage and self._strict_readonly_policy:
            raise VaultStartupStorageReadonlyError(
                details={"reason": "readonly_storage", "probe_name": self._probe_name, "policy": "strict_v1"},
            )

    def _is_storage_readonly(self) -> bool:
        """
        Назначение:
            Определить write-capability vault storage без изменения бизнес-данных.
        """
        try:
            with self._repository.transaction():
                return False
        except SecretStoreError as exc:
            if _is_readonly_store_error(exc):
                return True
            raise VaultStartupProbeCorruptedError(
                details={"reason": "storage_check_failed", "probe_name": self._probe_name},
            ) from exc

    def _load_probe(self) -> VaultProbeRecord | None:
        try:
            return self._repository.get_probe(probe_name=self._probe_name)
        except SecretReadError as exc:
            raise VaultStartupProbeCorruptedError(
                details={"reason": "probe_read_failed", "probe_name": self._probe_name},
            ) from exc

    def _create_probe(self, active_master_key: VaultMasterKey) -> VaultProbeRecord:
        now = getUtcNowIso()
        dek_record, dek_plaintext = self._ensure_active_dek(active_master_key=active_master_key, now=now)
        try:
            ciphertext = self._cipher.encrypt(
                plaintext=self._probe_payload,
                dek_plaintext=dek_plaintext,
                cipher_algo=self._cipher_algo,
            )
        except SecretKeyConfigError:
            raise
        except (SecretDecryptionError, SecretIntegrityError) as exc:
            raise VaultStartupProbeCorruptedError(
                details={"reason": "probe_encrypt_failed", "probe_name": self._probe_name},
            ) from exc

        probe_record = VaultProbeRecord(
            probe_name=self._probe_name,
            ciphertext=ciphertext,
            cipher_algo=self._cipher_algo,
            key_version=active_master_key.key_version,
            dek_version=dek_record.dek_version,
            created_at=now,
            updated_at=now,
        )
        try:
            self._repository.upsert_probe(probe_record)
        except SecretStoreError as exc:
            if _is_readonly_store_error(exc):
                raise VaultStartupUninitializedReadonlyError(
                    details={"reason": "probe_missing", "probe_name": self._probe_name},
                ) from exc
            raise VaultStartupProbeCorruptedError(
                details={"reason": "probe_write_failed", "probe_name": self._probe_name},
            ) from exc

        stored = self._load_probe()
        if stored is None:
            raise VaultStartupProbeCorruptedError(
                details={"reason": "probe_write_missing", "probe_name": self._probe_name},
            )
        return stored

    def _ensure_active_dek(self, *, active_master_key: VaultMasterKey, now: str) -> tuple[VaultDekRecord, bytes]:
        try:
            active_dek = self._repository.get_active_dek()
        except SecretReadError as exc:
            raise VaultStartupProbeCorruptedError(
                details={"reason": "dek_read_failed", "probe_name": self._probe_name},
            ) from exc

        if active_dek is not None:
            dek_plaintext = self._unwrap_dek(active_dek)
            return active_dek, dek_plaintext

        # Для Fernet-совместимого DEK нужен urlsafe base64 от 32 байт случайности.
        dek_plaintext = base64.urlsafe_b64encode(os.urandom(32))
        try:
            wrapped_dek = self._cipher.wrap_dek(
                dek_plaintext=dek_plaintext,
                master_key=active_master_key.key_material,
                wrap_algo=self._wrap_algo,
            )
        except SecretKeyConfigError:
            raise
        except (SecretDecryptionError, SecretIntegrityError) as exc:
            raise VaultStartupProbeCorruptedError(
                details={"reason": "dek_wrap_failed", "probe_name": self._probe_name},
            ) from exc

        dek_record = VaultDekRecord(
            dek_version=f"dek_{uuid4().hex}",
            wrapped_dek=wrapped_dek,
            wrap_algo=self._wrap_algo,
            wrap_key_version=active_master_key.key_version,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        try:
            self._repository.upsert_dek(dek_record)
        except SecretStoreError as exc:
            if _is_readonly_store_error(exc):
                raise VaultStartupUninitializedReadonlyError(
                    details={"reason": "probe_missing", "probe_name": self._probe_name},
                ) from exc
            raise VaultStartupProbeCorruptedError(
                details={"reason": "dek_write_failed", "probe_name": self._probe_name},
            ) from exc
        return dek_record, dek_plaintext

    def _verify_probe(self, probe: VaultProbeRecord) -> None:
        dek_record = self._load_probe_dek(probe)
        dek_plaintext = self._unwrap_dek(dek_record)
        try:
            probe_plaintext = self._cipher.decrypt(
                ciphertext=probe.ciphertext,
                dek_plaintext=dek_plaintext,
                cipher_algo=probe.cipher_algo,
            )
        except SecretDecryptionError as exc:
            raise VaultStartupKeyValidationError(
                details={
                    "reason": "probe_decrypt_failed",
                    "probe_name": probe.probe_name,
                    "key_version": probe.key_version,
                    "dek_version": probe.dek_version,
                },
            ) from exc
        except SecretIntegrityError as exc:
            raise VaultStartupProbeCorruptedError(
                details={
                    "reason": "probe_ciphertext_corrupted",
                    "probe_name": probe.probe_name,
                    "dek_version": probe.dek_version,
                },
            ) from exc

        if probe_plaintext != self._probe_payload:
            raise VaultStartupProbeCorruptedError(
                details={"reason": "probe_payload_mismatch", "probe_name": probe.probe_name},
            )

    def _load_probe_dek(self, probe: VaultProbeRecord) -> VaultDekRecord:
        try:
            dek_record = self._repository.get_dek(dek_version=probe.dek_version)
        except SecretReadError as exc:
            raise VaultStartupProbeCorruptedError(
                details={
                    "reason": "probe_dek_read_failed",
                    "probe_name": probe.probe_name,
                    "dek_version": probe.dek_version,
                },
            ) from exc
        if dek_record is None:
            raise VaultStartupProbeCorruptedError(
                details={
                    "reason": "probe_dek_missing",
                    "probe_name": probe.probe_name,
                    "dek_version": probe.dek_version,
                },
            )
        return dek_record

    def _unwrap_dek(self, dek_record: VaultDekRecord) -> bytes:
        for candidate in self._candidate_master_keys(dek_record.wrap_key_version):
            try:
                return self._cipher.unwrap_dek(
                    wrapped_dek=dek_record.wrapped_dek,
                    master_key=candidate.key_material,
                    wrap_algo=dek_record.wrap_algo,
                )
            except (SecretDecryptionError, SecretIntegrityError):
                continue
        raise VaultStartupKeyValidationError(
            details={
                "reason": "dek_unwrap_failed",
                "dek_version": dek_record.dek_version,
                "key_version": dek_record.wrap_key_version,
            },
        )

    def _candidate_master_keys(self, hint_key_version: str) -> list[VaultMasterKey]:
        candidates: list[VaultMasterKey] = []
        hinted = self._key_provider.find_key(hint_key_version)
        if hinted is not None:
            candidates.append(hinted)

        for key in self._key_provider.get_all_keys():
            if hinted is not None and key.key_version == hinted.key_version:
                continue
            candidates.append(key)
        return candidates

    def _validate_probe_record(self, probe: VaultProbeRecord) -> None:
        """
        Назначение:
            Проверить обязательные поля probe до decrypt-попытки.
        """
        if probe.probe_name != self._probe_name:
            raise VaultStartupProbeCorruptedError(
                details={"reason": "probe_name_mismatch", "probe_name": probe.probe_name},
            )
        if not probe.cipher_algo:
            raise VaultStartupProbeCorruptedError(
                details={"reason": "probe_cipher_algo_missing", "probe_name": probe.probe_name},
            )
        if not probe.key_version:
            raise VaultStartupProbeCorruptedError(
                details={"reason": "probe_key_version_missing", "probe_name": probe.probe_name},
            )
        if not probe.dek_version:
            raise VaultStartupProbeCorruptedError(
                details={"reason": "probe_dek_version_missing", "probe_name": probe.probe_name},
            )
        if _is_empty_ciphertext(probe.ciphertext):
            raise VaultStartupProbeCorruptedError(
                details={"reason": "probe_ciphertext_missing", "probe_name": probe.probe_name},
            )


def _is_readonly_store_error(exc: SecretStoreError) -> bool:
    details = exc.details if isinstance(exc.details, dict) else {}
    sqlite_error = str(details.get("sqlite_error", "")).lower()
    reason = str(details.get("reason", "")).lower()
    return "readonly" in sqlite_error or "read-only" in sqlite_error or "readonly" in reason


def _is_empty_ciphertext(value: bytes | str) -> bool:
    if isinstance(value, bytes):
        return len(value) == 0
    if isinstance(value, str):
        return value == ""
    return True

