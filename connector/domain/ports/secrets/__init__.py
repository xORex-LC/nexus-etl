"""Порты для работы с секретами."""

from connector.domain.ports.secrets.cipher import SecretCipherPort
from connector.domain.ports.secrets.key_provider import VaultKeyProviderPort, VaultMasterKey
from connector.domain.ports.secrets.locator import SecretLocatorPort
from connector.domain.ports.secrets.provider import SecretProviderProtocol, SecretStoreProtocol
from connector.domain.ports.secrets.retention import SecretApplyRetentionHookProtocol
from connector.domain.ports.secrets.repository import SecretVaultRepositoryPort

__all__ = [
    "SecretCipherPort",
    "SecretLocatorPort",
    "SecretProviderProtocol",
    "SecretApplyRetentionHookProtocol",
    "SecretStoreProtocol",
    "SecretVaultRepositoryPort",
    "VaultKeyProviderPort",
    "VaultMasterKey",
]
