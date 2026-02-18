"""
Назначение:
    Доменный контракт источника мастер-ключей Vault.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class VaultMasterKey:
    """
    Назначение:
        Представление мастер-ключа из keyring-конфигурации.

    Поля:
        key_version: стабильный идентификатор ключа.
        key_material: ключевой материал (в runtime памяти).
        is_active: признак активного ключа для wrap-операций.
    """

    key_version: str
    key_material: str
    is_active: bool = False


class VaultKeyProviderPort(Protocol):
    """
    Назначение:
        Контракт получения активного и fallback мастер-ключей.
    """

    def get_active_key(self) -> VaultMasterKey:
        """
        Контракт:
            Вернуть активный мастер-ключ для wrap-операций.
        """
        ...

    def get_all_keys(self) -> tuple[VaultMasterKey, ...]:
        """
        Контракт:
            Вернуть keyring в приоритетном порядке.
        """
        ...

    def find_key(self, key_version: str) -> VaultMasterKey | None:
        """
        Контракт:
            Найти мастер-ключ по версии.
        """
        ...

