"""
Назначение:
    Usecase-оркестрация unseal lifecycle операций vault-management.

Граница ответственности:
    - Оркестрирует init/status/rotate/rewrap поверх repository + crypto service.
    - Делегирует вывод master key в VaultUnsealService.
    - Делегирует wrap/unwrap DEK в SecretCipherPort.
    - Не знает о CLI prompts, ENV, файлах и конкретной SQLite реализации.
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

import structlog

from connector.common.time import get_utc_now_iso
from connector.domain.ports.secrets.cipher import SecretCipherPort
from connector.domain.ports.secrets.key_provider import VaultMasterKey
from connector.domain.ports.secrets.repository import SecretVaultRepositoryPort
from connector.domain.secrets.errors import (
    SecretDecryptionError,
    SecretIntegrityError,
    SecretKeyConfigError,
    SecretReadError,
    SecretStoreError,
    VaultManagementOperationError,
)
from connector.domain.secrets.models import VaultDekRecord, VaultUnsealMetadata
from connector.usecases.management.vault.contracts import (
    KeyVersionFactory,
    NowFactory,
    RunIdFactory,
    VaultPostVerifyProtocol,
    VaultUnsealServiceProtocol,
)
from connector.usecases.management.vault.models import (
    VaultKeyManagementResult,
    VaultKeyManagementStatus,
)


class VaultKeyManagementUseCase:
    """
    Назначение:
        Управлять lifecycle unseal-derived master wrapping key.

    Инварианты:
        - master key material не сохраняется на диске;
        - steady-state имеет одну active unseal metadata запись;
        - rotate меняет passphrase, создаёт новый derived key и rewrap-ит все DEK;
        - post-verify обязателен для операций, меняющих key/DEK metadata.
    """

    def __init__(
        self,
        *,
        repository: SecretVaultRepositoryPort,
        cipher: SecretCipherPort,
        unseal_service: VaultUnsealServiceProtocol,
        post_verify: VaultPostVerifyProtocol,
        now_utc: NowFactory = get_utc_now_iso,
        run_id_factory: RunIdFactory | None = None,
        key_version_factory: KeyVersionFactory | None = None,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._unseal_service = unseal_service
        self._post_verify = post_verify
        self._now_utc = now_utc
        self._run_id_factory = run_id_factory or _default_run_id
        self._key_version_factory = key_version_factory or _default_key_version
        self._logger = structlog.get_logger(__name__)

    def init_keyring(
        self,
        *,
        passphrase: str,
        run_id: str | None = None,
    ) -> VaultKeyManagementResult:
        """Инициализировать unseal metadata и startup probe."""
        effective_run_id = run_id or self._run_id_factory()
        self._logger.info("vault_mgmt_init", component="vault_management", op="start", run_id=effective_run_id)

        existing = self._repository.get_unseal_metadata()
        if existing is not None:
            raise VaultManagementOperationError(
                "Vault unseal metadata is already initialized",
                details={
                    "reason": "already_initialized",
                    "run_id": effective_run_id,
                    "active_key_version": existing.key_version,
                },
            )

        now = self._now_utc()
        metadata, active_key = self._unseal_service.create_metadata(
            passphrase=passphrase,
            key_version=self._unique_key_version(existing=()),
            now_utc=now,
        )
        try:
            self._repository.upsert_unseal_metadata(metadata)
            self._post_verify.ensure_ready((active_key,))
        except Exception as exc:  # noqa: BLE001
            self._mark_failed(run_id=effective_run_id, reason="init_failed")
            raise self._as_operation_error(
                exc,
                reason="init_failed",
                run_id=effective_run_id,
                operation="init",
            ) from exc

        self._mark_success(run_id=effective_run_id, reason="init_completed", rotated_at=now)
        self._logger.info(
            "vault_mgmt_init",
            component="vault_management",
            op="success",
            run_id=effective_run_id,
            active_key_version=active_key.key_version,
        )
        return VaultKeyManagementResult(
            operation="init",
            run_id=effective_run_id,
            active_key_version=active_key.key_version,
            dek_rewrapped_count=0,
            rotated_at=now,
        )

    def status(self) -> VaultKeyManagementStatus:
        """Вернуть read-only snapshot unseal metadata и DEK состояния."""
        metadata = self._repository.get_unseal_metadata()
        active_key_version = metadata.key_version if metadata is not None else None
        deks = self._repository.list_deks()
        rewrap_required = len(deks) if active_key_version is None else sum(
            1 for record in deks if record.wrap_key_version != active_key_version
        )
        return VaultKeyManagementStatus(
            key_versions=(active_key_version,) if active_key_version is not None else (),
            active_key_version=active_key_version,
            initialized=metadata is not None,
            dek_total=len(deks),
            dek_rewrap_required=rewrap_required,
            last_rotated_at=self._repository.get_last_rotated_at(),
            last_rotation_result=self._repository.get_last_rotation_result(),
            last_rotation_reason=self._repository.get_last_rotation_reason(),
            last_rotation_run_id=self._repository.get_last_rotation_run_id(),
        )

    def verify_unseal(self, *, passphrase: str) -> VaultMasterKey:
        """Проверить passphrase, startup readiness и вернуть runtime master key."""
        metadata = self._require_metadata(operation="status", run_id=None)
        active_key = self._unseal_service.derive_key(passphrase=passphrase, metadata=metadata)
        self._post_verify.ensure_ready((active_key,))
        return active_key

    def rotate_and_rewrap(
        self,
        *,
        current_passphrase: str,
        new_passphrase: str,
        run_id: str | None = None,
    ) -> VaultKeyManagementResult:
        """Сменить unseal passphrase и rewrap-ить все DEK новым derived key."""
        effective_run_id = run_id or self._run_id_factory()
        self._logger.info("vault_mgmt_rotate", component="vault_management", op="start", run_id=effective_run_id)

        metadata = self._require_metadata(operation="rotate", run_id=effective_run_id)
        old_key = self._unseal_service.derive_key(passphrase=current_passphrase, metadata=metadata)
        now = self._now_utc()
        new_metadata, new_key = self._unseal_service.create_metadata(
            passphrase=new_passphrase,
            key_version=self._unique_key_version(existing=(metadata.key_version,)),
            now_utc=now,
        )
        try:
            rewrapped = self._rewrap_in_transaction(
                active_key=new_key,
                candidate_keys=(old_key,),
                run_id=effective_run_id,
                in_progress_reason="rotate_in_progress",
                new_metadata=new_metadata,
            )
            self._post_verify.ensure_ready((new_key,))
        except Exception as exc:  # noqa: BLE001
            self._mark_failed(run_id=effective_run_id, reason="rotate_failed")
            raise self._as_operation_error(
                exc,
                reason="rotate_failed",
                run_id=effective_run_id,
                operation="rotate",
            ) from exc

        self._mark_success(run_id=effective_run_id, reason="rotate_completed", rotated_at=now)
        self._logger.info(
            "vault_mgmt_rotate",
            component="vault_management",
            op="success",
            run_id=effective_run_id,
            active_key_version=new_key.key_version,
            dek_rewrapped_count=rewrapped,
        )
        return VaultKeyManagementResult(
            operation="rotate",
            run_id=effective_run_id,
            active_key_version=new_key.key_version,
            dek_rewrapped_count=rewrapped,
            rotated_at=now,
        )

    def rewrap_all_dek(
        self,
        *,
        passphrase: str,
        run_id: str | None = None,
    ) -> VaultKeyManagementResult:
        """Rewrap всех DEK текущим active derived key без смены passphrase."""
        effective_run_id = run_id or self._run_id_factory()
        self._logger.info("vault_mgmt_rewrap", component="vault_management", op="start", run_id=effective_run_id)

        metadata = self._require_metadata(operation="rewrap", run_id=effective_run_id)
        active_key = self._unseal_service.derive_key(passphrase=passphrase, metadata=metadata)
        try:
            rewrapped = self._rewrap_in_transaction(
                active_key=active_key,
                candidate_keys=(active_key,),
                run_id=effective_run_id,
                in_progress_reason="rewrap_in_progress",
                new_metadata=None,
            )
            self._post_verify.ensure_ready((active_key,))
        except Exception as exc:  # noqa: BLE001
            self._mark_failed(run_id=effective_run_id, reason="rewrap_failed")
            raise self._as_operation_error(
                exc,
                reason="rewrap_failed",
                run_id=effective_run_id,
                operation="rewrap",
            ) from exc

        self._mark_success(run_id=effective_run_id, reason="rewrap_completed", rotated_at=None)
        return VaultKeyManagementResult(
            operation="rewrap",
            run_id=effective_run_id,
            active_key_version=active_key.key_version,
            dek_rewrapped_count=rewrapped,
            rotated_at=None,
        )

    def _rewrap_in_transaction(
        self,
        *,
        active_key: VaultMasterKey,
        candidate_keys: tuple[VaultMasterKey, ...],
        run_id: str,
        in_progress_reason: str,
        new_metadata: VaultUnsealMetadata | None,
    ) -> int:
        rewrapped = 0
        updated_at = self._now_utc()
        with self._repository.transaction():
            self._repository.set_last_rotation_run_id(run_id)
            self._repository.set_last_rotation_result(result="rotating", reason=in_progress_reason)
            if new_metadata is not None:
                self._repository.upsert_unseal_metadata(new_metadata)
            for record in self._repository.list_deks():
                dek_plaintext = self._unwrap_dek(record, candidate_keys)
                wrapped = self._cipher.wrap_dek(
                    dek_plaintext=dek_plaintext,
                    master_key=active_key.key_material,
                    wrap_algo=record.wrap_algo,
                )
                self._repository.upsert_dek(
                    VaultDekRecord(
                        dek_version=record.dek_version,
                        wrapped_dek=wrapped,
                        wrap_algo=record.wrap_algo,
                        wrap_key_version=active_key.key_version,
                        is_active=record.is_active,
                        created_at=record.created_at,
                        updated_at=updated_at,
                    )
                )
                rewrapped += 1
        return rewrapped

    def _unwrap_dek(self, record: VaultDekRecord, candidate_keys: tuple[VaultMasterKey, ...]) -> bytes:
        for key in candidate_keys:
            try:
                return self._cipher.unwrap_dek(
                    wrapped_dek=record.wrapped_dek,
                    master_key=key.key_material,
                    wrap_algo=record.wrap_algo,
                )
            except (SecretDecryptionError, SecretIntegrityError):
                continue
        raise VaultManagementOperationError(
            "Failed to unwrap DEK during vault-management operation",
            details={
                "reason": "dek_unwrap_failed",
                "dek_version": record.dek_version,
                "wrap_key_version": record.wrap_key_version,
            },
        )

    def _require_metadata(
        self,
        *,
        operation: Literal["status", "rotate", "rewrap"],
        run_id: str | None,
    ) -> VaultUnsealMetadata:
        metadata = self._repository.get_unseal_metadata()
        if metadata is not None:
            return metadata
        raise VaultManagementOperationError(
            "Vault unseal metadata is not initialized",
            details={"reason": "unseal_not_initialized", "operation": operation, "run_id": run_id},
        )

    def _unique_key_version(self, *, existing: tuple[str, ...]) -> str:
        existing_versions = set(existing)
        for _ in range(10):
            key_version = self._key_version_factory()
            if key_version not in existing_versions:
                return key_version
        raise VaultManagementOperationError(
            "Failed to generate unique master key version",
            details={"reason": "key_version_collision"},
        )

    def _mark_success(self, *, run_id: str, reason: str, rotated_at: str | None) -> None:
        self._repository.set_last_rotation_run_id(run_id)
        self._repository.set_last_rotation_result(result="ok", reason=reason)
        if rotated_at is not None:
            self._repository.set_last_rotated_at(rotated_at)

    def _mark_failed(self, *, run_id: str, reason: str) -> None:
        self._repository.set_last_rotation_run_id(run_id)
        self._repository.set_last_rotation_result(result="failed", reason=reason)

    def _as_operation_error(
        self,
        exc: Exception,
        *,
        reason: str,
        run_id: str,
        operation: Literal["init", "rotate", "rewrap"],
    ) -> VaultManagementOperationError:
        if isinstance(exc, VaultManagementOperationError):
            return exc
        if isinstance(exc, (SecretReadError, SecretStoreError)):
            resolved_reason = "storage_error"
        elif isinstance(exc, (SecretKeyConfigError, SecretDecryptionError, SecretIntegrityError)):
            resolved_reason = "crypto_error"
        else:
            resolved_reason = reason
        return VaultManagementOperationError(
            "Vault management operation failed",
            details={
                "reason": resolved_reason,
                "operation": operation,
                "run_id": run_id,
                "error_type": type(exc).__name__,
            },
        )


def _default_run_id() -> str:
    return f"vault_mgmt_{uuid4().hex}"


def _default_key_version() -> str:
    return f"mk_{uuid4().hex}"


__all__ = ["VaultKeyManagementUseCase"]
