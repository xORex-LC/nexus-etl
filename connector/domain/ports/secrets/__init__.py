"""Порты для работы с секретами."""

from connector.domain.ports.secrets.provider import SecretProviderProtocol, SecretStoreProtocol

__all__ = [
    "SecretProviderProtocol",
    "SecretStoreProtocol",
]
