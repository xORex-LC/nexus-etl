from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connector.domain.ports.cache.repository import CacheRepositoryProtocol
from connector.domain.ports.secrets.provider import SecretStoreProtocol
from connector.domain.ports.transform.dictionaries import DictionaryProviderPort


@dataclass(frozen=True)
class EmployeesEnrichDependencies:
    """
    Назначение:
        Набор зависимостей enrich для employees.
    """

    conn: Any
    cache_repo: CacheRepositoryProtocol
    secret_store: SecretStoreProtocol | None = None
    dictionaries: DictionaryProviderPort | None = None
