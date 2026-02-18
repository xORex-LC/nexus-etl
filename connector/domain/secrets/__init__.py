"""Доменные модели и ошибки Vault-подсистемы."""

from connector.domain.secrets.errors import (
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
from connector.domain.secrets.secret_vault_read_service import SecretVaultReadService

__all__ = [
    "SecretDecryptionError",
    "SecretIntegrityError",
    "SecretKeyConfigError",
    "SecretNotFoundError",
    "SecretReadError",
    "SecretStoreError",
    "VaultDekRecord",
    "VaultDomainError",
    "VaultProbeRecord",
    "VaultSecretRecord",
    "SecretVaultReadService",
    "VaultStartupKeyValidationError",
    "VaultStartupProbeCorruptedError",
    "VaultStartupStorageReadonlyError",
    "VaultStartupUninitializedReadonlyError",
]
