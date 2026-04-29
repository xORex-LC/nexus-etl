"""
Назначение:
    Контракты и фабрики времени/ID для vault-management usecase.

Граница ответственности:
    - Определяет абстракции взаимодействия (managed keyring store, post-verify).
    - Не содержит orchestration-логики и инфраструктурной реализации.
"""

from __future__ import annotations

from typing import Callable, Protocol

from connector.domain.ports.secrets.key_provider import VaultMasterKey
from connector.domain.secrets.models import VaultUnsealMetadata
from connector.usecases.management.vault.models import VaultKeyManagementResult, VaultKeyManagementStatus

RunIdFactory = Callable[[], str]
NowFactory = Callable[[], str]
KeyVersionFactory = Callable[[], str]


class VaultKeyManagementProtocol(Protocol):
    """Контракт key-management операций для maintenance usecase."""

    def status(self) -> VaultKeyManagementStatus: ...

    def rotate_and_rewrap(
        self,
        *,
        current_passphrase: str,
        new_passphrase: str,
        run_id: str | None = None,
    ) -> VaultKeyManagementResult: ...


class VaultPostVerifyProtocol(Protocol):
    """Контракт post-operation verify шага."""

    def ensure_ready(self, keyring: tuple[VaultMasterKey, ...]) -> None:
        ...


class VaultUnsealServiceProtocol(Protocol):
    """Контракт crypto-сервиса unseal-модели."""

    def create_metadata(
        self,
        *,
        passphrase: str,
        key_version: str,
        now_utc: str,
    ) -> tuple[VaultUnsealMetadata, VaultMasterKey]:
        ...

    def derive_key(self, *, passphrase: str, metadata: VaultUnsealMetadata) -> VaultMasterKey:
        ...


__all__ = [
    "RunIdFactory",
    "NowFactory",
    "KeyVersionFactory",
    "VaultKeyManagementProtocol",
    "VaultPostVerifyProtocol",
    "VaultUnsealServiceProtocol",
]
