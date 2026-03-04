"""
Назначение:
    Доменные исключения Vault-подсистемы с кодами для diagnostics/reporting.
"""

from __future__ import annotations

from typing import Any


class VaultDomainError(RuntimeError):
    """
    Назначение:
        Базовая ошибка Vault-домена.

    Контракт:
        - code: доменный/операционный код ошибки.
        - details: безопасные служебные детали без secret leakage.
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


class SecretKeyConfigError(VaultDomainError):
    """
    Назначение:
        Ошибка конфигурации keyring/мастер-ключей.
    """

    def __init__(self, message: str = "Invalid vault key configuration", *, details: dict[str, Any] | None = None):
        super().__init__(code="VAULT_STARTUP_KEY_CONFIG_ERROR", message=message, details=details)


class VaultStartupKeyValidationError(VaultDomainError):
    """
    Назначение:
        Ошибка startup decrypt probe (несовместимый keyring).
    """

    def __init__(
        self,
        message: str = "Vault startup key validation failed",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="VAULT_STARTUP_KEY_VALIDATION_ERROR", message=message, details=details)


class VaultStartupProbeCorruptedError(VaultDomainError):
    """
    Назначение:
        Ошибка структуры/целостности startup probe.
    """

    def __init__(
        self,
        message: str = "Vault startup probe is corrupted",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="VAULT_STARTUP_PROBE_CORRUPTED", message=message, details=details)


class VaultStartupStorageReadonlyError(VaultDomainError):
    """
    Назначение:
        Ошибка startup strict-policy для readonly storage.
    """

    def __init__(
        self,
        message: str = "Vault storage is readonly",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="VAULT_STARTUP_STORAGE_READONLY", message=message, details=details)


class VaultStartupUninitializedReadonlyError(VaultDomainError):
    """
    Назначение:
        Ошибка startup: probe отсутствует и storage readonly.
    """

    def __init__(
        self,
        message: str = "Vault storage is readonly and probe is missing",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="VAULT_STARTUP_UNINITIALIZED_READONLY", message=message, details=details)


class SecretStoreError(VaultDomainError):
    """
    Назначение:
        Ошибка записи секрета в storage boundary.
    """

    def __init__(self, message: str = "Failed to store secret", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code="SECRET_STORE_ERROR", message=message, details=details)


class SecretReadError(VaultDomainError):
    """
    Назначение:
        Ошибка чтения секрета из storage boundary.
    """

    def __init__(self, message: str = "Failed to read secret", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code="SECRET_READ_ERROR", message=message, details=details)


class SecretDecryptionError(VaultDomainError):
    """
    Назначение:
        Ошибка дешифрования секрета/DEK.
    """

    def __init__(self, message: str = "Failed to decrypt secret", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code="SECRET_DECRYPTION_ERROR", message=message, details=details)


class SecretIntegrityError(VaultDomainError):
    """
    Назначение:
        Ошибка проверки целостности ciphertext/metadata.
    """

    def __init__(
        self,
        message: str = "Secret integrity check failed",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(code="SECRET_INTEGRITY_ERROR", message=message, details=details)


class SecretNotFoundError(VaultDomainError):
    """
    Назначение:
        Секрет не найден по locator контексту.
    """

    def __init__(self, message: str = "Secret not found", *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code="SECRET_NOT_FOUND", message=message, details=details)


class VaultAdminPasswordConfigError(VaultDomainError):
    """
    Назначение:
        Ошибка конфигурации password-gate для manual vault-management операций.
    """

    def __init__(
        self,
        message: str = "Vault admin password gate is misconfigured",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code="VAULT_MANAGEMENT_ADMIN_PASSWORD_CONFIG_ERROR",
            message=message,
            details=details,
        )


class VaultAdminAccessDeniedError(VaultDomainError):
    """
    Назначение:
        Ошибка доступа: пароль администратора vault не прошёл проверку.
    """

    def __init__(
        self,
        message: str = "Vault admin access denied",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            code="VAULT_MANAGEMENT_ADMIN_ACCESS_DENIED",
            message=message,
            details=details,
        )
