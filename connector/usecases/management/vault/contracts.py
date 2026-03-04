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


class VaultPostVerifyProtocol(Protocol):
    """Контракт post-operation verify шага."""

    def ensure_ready(self, keyring: tuple[VaultMasterKey, ...]) -> None:
        ...


__all__ = [
    "RunIdFactory",
    "NowFactory",
    "KeyMaterialFactory",
    "KeyVersionFactory",
    "VaultManagedKeyringStoreProtocol",
    "VaultPostVerifyProtocol",
]

