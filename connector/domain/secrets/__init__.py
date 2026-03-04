"""Доменные модели и ошибки Vault-подсистемы."""

from connector.domain.secrets.errors import (
    VaultAdminAccessDeniedError,
    VaultAdminPasswordConfigError,
    SecretDecryptionError,
    SecretIntegrityError,
    SecretKeyConfigError,
    SecretNotFoundError,
    SecretReadError,
    SecretStoreError,
    VaultDomainError,
    VaultStartupKeyValidationError,
    VaultStartupProbeCorruptedError,
    VaultStartupStorageReadonlyError,
    VaultStartupUninitializedReadonlyError,
)
from connector.domain.secrets.models import VaultDekRecord, VaultProbeRecord, VaultSecretRecord

__all__ = [
    "SecretDecryptionError",
    "SecretIntegrityError",
    "SecretKeyConfigError",
    "SecretNotFoundError",
    "SecretReadError",
    "SecretStoreError",
    "VaultAdminAccessDeniedError",
    "VaultAdminPasswordConfigError",
    "VaultDekRecord",
    "VaultDomainError",
    "VaultProbeRecord",
    "VaultSecretRecord",
    "VaultStartupKeyValidationError",
    "VaultStartupProbeCorruptedError",
    "VaultStartupStorageReadonlyError",
    "VaultStartupUninitializedReadonlyError",
]
