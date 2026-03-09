"""
Назначение:
    Usecase-оркестрация lifecycle-операций vault-management (init/status/rotate/rewrap/delete-key).

Граница ответственности:
    - Оркестрирует шаги и инварианты lifecycle протокола.
    - Делегирует IO/хранение в repository + managed keyring store.
    - Делегирует криптооперации unwrap/wrap в SecretCipherPort.
    - Делегирует post-verify в VaultPostVerifyProtocol.
    - Не содержит CLI/delivery-логики и не знает о флагах команд.
"""

from __future__ import annotations

from typing import Literal
from uuid import uuid4

import structlog

from connector.common.time import getUtcNowIso
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
from connector.domain.secrets.models import VaultDekRecord
from connector.usecases.management.vault.contracts import (
    KeyMaterialFactory,
    KeyVersionFactory,
    NowFactory,
    RunIdFactory,
    VaultManagedKeyringStoreProtocol,
    VaultPostVerifyProtocol,
)
from connector.usecases.management.vault.models import (
    VaultKeyManagementResult,
    VaultKeyManagementStatus,
)


class VaultKeyManagementUseCase:
    """
    Назначение:
        Оркестратор lifecycle-операций key-management для vault.

    Инварианты:
        - steady-state хранит только один active master key;
        - rotate использует crash-safe bridge keyring на in-flight шаге;
        - все DEK rewrap-ятся в `BEGIN IMMEDIATE` transaction;
        - post-verify обязателен для операций, меняющих keyring/DEK.
    """

    def __init__(
        self,
        *,
        repository: SecretVaultRepositoryPort,
        cipher: SecretCipherPort,
        keyring_store: VaultManagedKeyringStoreProtocol,
        post_verify: VaultPostVerifyProtocol,
        now_utc: NowFactory = getUtcNowIso,
        run_id_factory: RunIdFactory | None = None,
        key_material_factory: KeyMaterialFactory | None = None,
        key_version_factory: KeyVersionFactory | None = None,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._keyring_store = keyring_store
        self._post_verify = post_verify
        self._now_utc = now_utc
        self._run_id_factory = run_id_factory or _default_run_id
        self._key_material_factory = key_material_factory or _default_key_material
        self._key_version_factory = key_version_factory or _default_key_version
        self._logger = structlog.get_logger(__name__)

    def init_keyring(
        self,
        *,
        run_id: str | None = None,
        initial_keyring: tuple[VaultMasterKey, ...] | None = None,
    ) -> VaultKeyManagementResult:
        """Назначение:
            Инициализировать первый keyring (разрешено только при отсутствии active key).
        """
        effective_run_id = run_id or self._run_id_factory()
        self._logger.info(
            "vault_mgmt_init",
            component="vault_management",
            op="start",
            run_id=effective_run_id,
        )

        with self._keyring_store.lifecycle_lock():
            existing = self._load_keyring_safe(treat_empty_as_absent=True)
            if existing:
                raise VaultManagementOperationError(
                    "Vault keyring is already initialized",
                    details={
                        "reason": "already_initialized",
                        "run_id": effective_run_id,
                        "active_key_version": existing[0].key_version,
                    },
                )

            new_keyring, init_reason = self._resolve_initial_keyring(
                existing_keyring=existing,
                initial_keyring=initial_keyring,
            )
            active_key = new_keyring[0]
            try:
                self._keyring_store.save_keyring(new_keyring)
                self._post_verify.ensure_ready(new_keyring)
            except Exception as exc:  # noqa: BLE001
                self._mark_failed(run_id=effective_run_id, reason="init_failed")
                self._logger.error(
                    "vault_mgmt_init",
                    component="vault_management",
                    op="failed",
                    run_id=effective_run_id,
                    reason="init_failed",
                    error_type=type(exc).__name__,
                )
                raise self._as_operation_error(
                    exc,
                    reason="init_failed",
                    run_id=effective_run_id,
                    operation="init",
                ) from exc

            rotated_at = self._now_utc()
            self._mark_success(
                run_id=effective_run_id,
                reason=init_reason,
                rotated_at=rotated_at,
            )
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
                bridge_key_count=len(new_keyring),
                final_key_count=len(new_keyring),
                rotated_at=rotated_at,
            )

    def status(self) -> VaultKeyManagementStatus:
        """Назначение:
            Вернуть read-only статус keyring/DEK/metadata для vault-management.

        Примечание:
            Снимок является best-effort и не гарантирует атомарности —
            keyring читается под lifecycle_lock, а DEK и metadata вне лока.
            Для операций, требующих согласованности, используется lifecycle_lock
            на протяжении всей операции (rotate, rewrap, finalize).
        """
        with self._keyring_store.lifecycle_lock():
            keyring = self._load_keyring_safe(treat_empty_as_absent=False)

        active_key = keyring[0] if keyring else None
        deks = self._repository.list_deks()
        rewrap_required = len(deks) if active_key is None else sum(
            1 for record in deks if record.wrap_key_version != active_key.key_version
        )

        return VaultKeyManagementStatus(
            key_versions=tuple(item.key_version for item in keyring),
            active_key_version=active_key.key_version if active_key is not None else None,
            bridge_keyring=len(keyring) > 1,
            dek_total=len(deks),
            dek_rewrap_required=rewrap_required,
            last_rotated_at=self._repository.get_last_rotated_at(),
            last_rotation_result=self._repository.get_last_rotation_result(),
            last_rotation_reason=self._repository.get_last_rotation_reason(),
            last_rotation_run_id=self._repository.get_last_rotation_run_id(),
        )

    def rotate_and_rewrap(self, *, run_id: str | None = None) -> VaultKeyManagementResult:
        """Назначение:
            Выполнить crash-safe rotate protocol с bridge keyring и rewrap всех DEK.

        Алгоритм:
            1) Взять lifecycle lock.
            2) Сгенерировать новый active key.
            3) Сохранить bridge keyring (`new + current keyring`).
            4) В `BEGIN IMMEDIATE` rewrap всех DEK на `new`.
            5) Сохранить финальный keyring (`new` only).
            6) Выполнить post-verify через VaultStartupGuard.
            7) Зафиксировать metadata `ok/failed`.
        """
        effective_run_id = run_id or self._run_id_factory()
        self._logger.info(
            "vault_mgmt_rotate",
            component="vault_management",
            op="start",
            run_id=effective_run_id,
        )

        with self._keyring_store.lifecycle_lock():
            keyring = self._require_keyring(run_id=effective_run_id, operation="rotate")
            new_key = self._build_new_active_key(keyring)
            bridge_keyring = self._build_bridge_keyring(new_key, keyring)
            self._keyring_store.save_keyring(bridge_keyring)

            try:
                rewrapped = self._rewrap_in_transaction(
                    active_key=new_key,
                    keyring=bridge_keyring,
                    run_id=effective_run_id,
                    in_progress_reason="rotate_in_progress",
                )
                self._keyring_store.save_keyring((new_key,))
                self._post_verify.ensure_ready((new_key,))
            except Exception as exc:  # noqa: BLE001
                self._mark_failed(run_id=effective_run_id, reason="rotate_failed")
                self._logger.error(
                    "vault_mgmt_rotate",
                    component="vault_management",
                    op="failed",
                    run_id=effective_run_id,
                    reason="rotate_failed",
                    error_type=type(exc).__name__,
                    bridge_key_count=len(bridge_keyring),
                )
                raise self._as_operation_error(
                    exc,
                    reason="rotate_failed",
                    run_id=effective_run_id,
                    operation="rotate",
                    extra={"bridge_key_count": len(bridge_keyring)},
                ) from exc

            rotated_at = self._now_utc()
            self._mark_success(
                run_id=effective_run_id,
                reason="rotate_completed",
                rotated_at=rotated_at,
            )
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
                bridge_key_count=len(bridge_keyring),
                final_key_count=1,
                rotated_at=rotated_at,
            )

    def rewrap_all_dek(self, *, run_id: str | None = None) -> VaultKeyManagementResult:
        """Назначение:
            Rewrap всех DEK текущим active key без смены keyring.
        """
        effective_run_id = run_id or self._run_id_factory()
        self._logger.info(
            "vault_mgmt_rewrap",
            component="vault_management",
            op="start",
            run_id=effective_run_id,
        )

        with self._keyring_store.lifecycle_lock():
            keyring = self._require_keyring(run_id=effective_run_id, operation="rewrap")
            active_key = keyring[0]
            try:
                rewrapped = self._rewrap_in_transaction(
                    active_key=active_key,
                    keyring=keyring,
                    run_id=effective_run_id,
                    in_progress_reason="rewrap_in_progress",
                )
                self._post_verify.ensure_ready((active_key,))
            except Exception as exc:  # noqa: BLE001
                self._mark_failed(run_id=effective_run_id, reason="rewrap_failed")
                self._logger.error(
                    "vault_mgmt_rewrap",
                    component="vault_management",
                    op="failed",
                    run_id=effective_run_id,
                    reason="rewrap_failed",
                    error_type=type(exc).__name__,
                )
                raise self._as_operation_error(
                    exc,
                    reason="rewrap_failed",
                    run_id=effective_run_id,
                    operation="rewrap",
                ) from exc

            self._mark_success(run_id=effective_run_id, reason="rewrap_completed", rotated_at=None)
            self._logger.info(
                "vault_mgmt_rewrap",
                component="vault_management",
                op="success",
                run_id=effective_run_id,
                active_key_version=active_key.key_version,
                dek_rewrapped_count=rewrapped,
            )
            return VaultKeyManagementResult(
                operation="rewrap",
                run_id=effective_run_id,
                active_key_version=active_key.key_version,
                dek_rewrapped_count=rewrapped,
                bridge_key_count=len(keyring),
                final_key_count=len(keyring),
                rotated_at=None,
            )

    def delete_key(self, *, run_id: str | None = None) -> VaultKeyManagementResult:
        """Назначение:
            Выполнить delete-key только как replace-flow (`rotate + rewrap`).
        """
        effective_run_id = run_id or self._run_id_factory()
        self._logger.info(
            "vault_mgmt_delete",
            component="vault_management",
            op="start",
            run_id=effective_run_id,
            mode="replace_flow",
        )
        result = self.rotate_and_rewrap(run_id=effective_run_id)
        self._logger.info(
            "vault_mgmt_delete",
            component="vault_management",
            op="success",
            run_id=result.run_id,
            active_key_version=result.active_key_version,
        )
        return VaultKeyManagementResult(
            operation="delete_key",
            run_id=result.run_id,
            active_key_version=result.active_key_version,
            dek_rewrapped_count=result.dek_rewrapped_count,
            bridge_key_count=result.bridge_key_count,
            final_key_count=result.final_key_count,
            rotated_at=result.rotated_at,
        )

    def finalize_inflight_bridge(self, *, run_id: str | None = None) -> VaultKeyManagementResult | None:
        """Назначение:
            Финализировать in-flight bridge keyring (`new,old...`) в single-key steady-state.

        Контракт:
            - если bridge отсутствует (`len(keyring) <= 1`), вернуть `None`;
            - при наличии bridge выполнить rewrap всех DEK на первый ключ keyring;
            - после успешного rewrap сохранить финальный keyring (`new` only) и выполнить post-verify.
        """
        effective_run_id = run_id or self._run_id_factory()
        self._logger.info(
            "vault_mgmt_rotate",
            component="vault_management",
            op="start",
            run_id=effective_run_id,
            mode="bridge_finalize",
        )

        with self._keyring_store.lifecycle_lock():
            keyring = self._require_keyring(run_id=effective_run_id, operation="rotate")
            bridge_key_count = len(keyring)
            if bridge_key_count <= 1:
                self._logger.info(
                    "vault_mgmt_rotate",
                    component="vault_management",
                    op="success",
                    run_id=effective_run_id,
                    mode="bridge_finalize",
                    reason="bridge_not_detected",
                )
                return None

            active_key = keyring[0]
            try:
                rewrapped = self._rewrap_in_transaction(
                    active_key=active_key,
                    keyring=keyring,
                    run_id=effective_run_id,
                    in_progress_reason="bridge_finalize_in_progress",
                )
                self._keyring_store.save_keyring((active_key,))
                self._post_verify.ensure_ready((active_key,))
            except Exception as exc:  # noqa: BLE001
                self._mark_failed(run_id=effective_run_id, reason="bridge_finalize_failed")
                self._logger.error(
                    "vault_mgmt_rotate",
                    component="vault_management",
                    op="failed",
                    run_id=effective_run_id,
                    mode="bridge_finalize",
                    reason="bridge_finalize_failed",
                    error_type=type(exc).__name__,
                    bridge_key_count=bridge_key_count,
                )
                raise self._as_operation_error(
                    exc,
                    reason="bridge_finalize_failed",
                    run_id=effective_run_id,
                    operation="rotate",
                    extra={"bridge_key_count": bridge_key_count, "mode": "bridge_finalize"},
                ) from exc

            rotated_at = self._now_utc()
            self._mark_success(
                run_id=effective_run_id,
                reason="bridge_finalize_completed",
                rotated_at=rotated_at,
            )
            self._logger.info(
                "vault_mgmt_rotate",
                component="vault_management",
                op="success",
                run_id=effective_run_id,
                mode="bridge_finalize",
                active_key_version=active_key.key_version,
                dek_rewrapped_count=rewrapped,
            )
            return VaultKeyManagementResult(
                operation="rotate",
                run_id=effective_run_id,
                active_key_version=active_key.key_version,
                dek_rewrapped_count=rewrapped,
                bridge_key_count=bridge_key_count,
                final_key_count=1,
                rotated_at=rotated_at,
            )

    def _rewrap_in_transaction(
        self,
        *,
        active_key: VaultMasterKey,
        keyring: tuple[VaultMasterKey, ...],
        run_id: str,
        in_progress_reason: str,
    ) -> int:
        """Назначение:
            Rewrap всех DEK на active master key внутри одной write-транзакции.
        """
        rewrapped = 0
        updated_at = self._now_utc()
        with self._repository.transaction():
            self._repository.set_last_rotation_run_id(run_id)
            self._repository.set_last_rotation_result(result="rotating", reason=in_progress_reason)
            records = self._repository.list_deks()
            for record in records:
                dek_plaintext = self._unwrap_dek(record, keyring)
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

    def _unwrap_dek(self, record: VaultDekRecord, keyring: tuple[VaultMasterKey, ...]) -> bytes:
        for key in self._candidate_keys(record.wrap_key_version, keyring):
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

    def _candidate_keys(
        self,
        wrap_key_version: str,
        keyring: tuple[VaultMasterKey, ...],
    ) -> tuple[VaultMasterKey, ...]:
        hinted: VaultMasterKey | None = None
        for item in keyring:
            if item.key_version == wrap_key_version:
                hinted = item
                break
        if hinted is None:
            return keyring
        return (hinted,) + tuple(item for item in keyring if item.key_version != hinted.key_version)

    def _build_new_active_key(self, existing_keyring: tuple[VaultMasterKey, ...]) -> VaultMasterKey:
        existing_versions = {item.key_version for item in existing_keyring}
        for _ in range(10):
            key_version = self._key_version_factory()
            if key_version not in existing_versions:
                return VaultMasterKey(
                    key_version=key_version,
                    key_material=self._key_material_factory(),
                    is_active=True,
                )
        raise VaultManagementOperationError(
            "Failed to generate unique master key version",
            details={"reason": "key_version_collision"},
        )

    def _build_bridge_keyring(
        self,
        new_key: VaultMasterKey,
        existing_keyring: tuple[VaultMasterKey, ...],
    ) -> tuple[VaultMasterKey, ...]:
        fallback = tuple(item for item in existing_keyring if item.key_version != new_key.key_version)
        return (new_key,) + fallback

    def _resolve_initial_keyring(
        self,
        *,
        existing_keyring: tuple[VaultMasterKey, ...],
        initial_keyring: tuple[VaultMasterKey, ...] | None,
    ) -> tuple[tuple[VaultMasterKey, ...], str]:
        if initial_keyring is None:
            new_key = self._build_new_active_key(existing_keyring)
            return (new_key,), "init_completed"

        if not initial_keyring:
            raise VaultManagementOperationError(
                "Initial keyring cannot be empty",
                details={"reason": "empty_initial_keyring"},
            )
        if len(initial_keyring) != 1:
            raise VaultManagementOperationError(
                "Initial keyring must contain exactly one active key",
                details={
                    "reason": "initial_keyring_requires_single_key",
                    "key_count": len(initial_keyring),
                },
            )
        imported = initial_keyring[0]
        normalized = VaultMasterKey(
            key_version=imported.key_version,
            key_material=imported.key_material,
            is_active=True,
        )
        return (normalized,), "init_import_existing_env_completed"

    def _mark_success(self, *, run_id: str, reason: str, rotated_at: str | None) -> None:
        self._repository.set_last_rotation_run_id(run_id)
        self._repository.set_last_rotation_result(result="ok", reason=reason)
        if rotated_at is not None:
            self._repository.set_last_rotated_at(rotated_at)

    def _mark_failed(self, *, run_id: str, reason: str) -> None:
        self._repository.set_last_rotation_run_id(run_id)
        self._repository.set_last_rotation_result(result="failed", reason=reason)

    def _load_keyring_safe(self, *, treat_empty_as_absent: bool) -> tuple[VaultMasterKey, ...]:
        """Загрузить keyring, подавляя ожидаемые ошибки конфигурации.

        Аргумент treat_empty_as_absent контролирует обработку пустого keyring:
          - True  (init): empty_keyring считается "ещё не инициализирован" → вернуть ().
          - False (status/require): empty_keyring — ошибка конфигурации → пробросить.
        """
        try:
            return self._keyring_store.load_keyring()
        except SecretKeyConfigError as exc:
            reason = str(exc.details.get("reason", ""))
            allowed = {"managed_env_file_missing", "managed_env_var_missing"}
            if treat_empty_as_absent:
                allowed = allowed | {"empty_keyring"}
            if reason in allowed:
                return ()
            raise

    def _require_keyring(
        self,
        *,
        run_id: str,
        operation: Literal["rotate", "rewrap"],
    ) -> tuple[VaultMasterKey, ...]:
        keyring = self._load_keyring_safe(treat_empty_as_absent=False)
        if keyring:
            return keyring
        raise VaultManagementOperationError(
            "Vault keyring is not initialized",
            details={
                "reason": "keyring_not_initialized",
                "operation": operation,
                "run_id": run_id,
            },
        )

    def _as_operation_error(
        self,
        exc: Exception,
        *,
        reason: str,
        run_id: str,
        operation: Literal["init", "rotate", "rewrap"],
        extra: dict[str, object] | None = None,
    ) -> VaultManagementOperationError:
        if isinstance(exc, VaultManagementOperationError):
            return exc
        if isinstance(exc, (SecretReadError, SecretStoreError)):
            resolved_reason = "storage_error"
        elif isinstance(exc, (SecretKeyConfigError, SecretDecryptionError, SecretIntegrityError)):
            resolved_reason = "crypto_error"
        else:
            resolved_reason = reason
        details: dict[str, object] = {
            "reason": resolved_reason,
            "operation": operation,
            "run_id": run_id,
            "error_type": type(exc).__name__,
        }
        if extra:
            details.update(extra)
        return VaultManagementOperationError(
            "Vault management operation failed",
            details=details,
        )


def _default_run_id() -> str:
    return f"vault_mgmt_{uuid4().hex}"


def _default_key_version() -> str:
    return f"mk_{uuid4().hex}"


def _default_key_material() -> str:
    from cryptography.fernet import Fernet

    return Fernet.generate_key().decode("utf-8")


__all__ = ["VaultKeyManagementUseCase"]
