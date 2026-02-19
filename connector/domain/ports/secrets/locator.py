"""
Назначение:
    Доменный контракт построения locator hash для адресации секрета.
"""

from __future__ import annotations

from typing import Any, Protocol


class SecretLocatorPort(Protocol):
    """
    Назначение:
        Контракт детерминированного построения ключа адресации секрета.

    Инварианты:
        - одинаковый вход -> одинаковый hash;
        - версия locator алгоритма должна быть явной частью контракта.
    """

    def build_locator_hash(
        self,
        *,
        dataset: str,
        field: str,
        source_ref: dict[str, Any] | None,
        locator_version: str = "v1",
    ) -> str:
        """
        Контракт:
            Построить hash locator для read/write путей Vault.
        """
        ...

    def supported_versions(self) -> tuple[str, ...]:
        """
        Контракт:
            Вернуть список поддерживаемых locator-версий в порядке приоритета.
        """
        ...

