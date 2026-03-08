"""
Назначение:
    Контракты и фабрики времени/ID для vault-management usecase.

Граница ответственности:
    - Определяет абстракции взаимодействия (managed keyring store, post-verify).
    - Не содержит orchestration-логики и инфраструктурной реализации.
"""

from __future__ import annotations

from typing import Callable, ContextManager, Protocol

from connector.domain.ports.secrets.key_provider import VaultMasterKey
from connector.usecases.management.vault.models import VaultKeyManagementResult, VaultKeyManagementStatus

RunIdFactory = Callable[[], str]
NowFactory = Callable[[], str]
KeyMaterialFactory = Callable[[], str]
KeyVersionFactory = Callable[[], str]


class VaultManagedKeyringStoreProtocol(Protocol):
    """Контракт managed keyring store для lifecycle usecase."""

    def lifecycle_lock(self) -> ContextManager[None]:
        ...

    def load_keyring(self) -> tuple[VaultMasterKey, ...]:
        ...

    def save_keyring(self, keys: tuple[VaultMasterKey, ...]) -> None:
        ...


class VaultKeyManagementProtocol(Protocol):
    """Контракт key-management операций для maintenance usecase."""

    def status(self) -> VaultKeyManagementStatus: ...

    def rotate_and_rewrap(self, *, run_id: str | None = None) -> VaultKeyManagementResult: ...

    def finalize_inflight_bridge(self, *, run_id: str | None = None) -> VaultKeyManagementResult | None: ...


class VaultPostVerifyProtocol(Protocol):
    """Контракт post-operation verify шага."""

    def ensure_ready(self, keyring: tuple[VaultMasterKey, ...]) -> None:
        ...


__all__ = [
    "RunIdFactory",
    "NowFactory",
    "KeyMaterialFactory",
    "KeyVersionFactory",
    "VaultKeyManagementProtocol",
    "VaultManagedKeyringStoreProtocol",
    "VaultPostVerifyProtocol",
]

