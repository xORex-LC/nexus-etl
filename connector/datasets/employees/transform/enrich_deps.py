from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connector.domain.ports.cache_repository import CacheRepositoryProtocol
from connector.domain.ports.secrets import SecretStoreProtocol


@dataclass(frozen=True)
class EmployeesEnrichDependencies:
    """
    Назначение:
        Набор зависимостей enrich для employees.
    """

    conn: Any
    cache_repo: CacheRepositoryProtocol
    secret_store: SecretStoreProtocol | None = None

    def find_user_by_id(self, resource_id: str) -> dict[str, Any] | None:
        return self.cache_repo.find_one("employees", {"_id": resource_id}, include_deleted=True)

    def find_user_by_usr_org_tab_num(self, tab_num: str) -> dict[str, Any] | None:
        return self.cache_repo.find_one("employees", {"usr_org_tab_num": tab_num}, include_deleted=True)

    def find_org_by_ouid(self, ouid: int) -> dict[str, Any] | None:
        return self.cache_repo.find_one("organizations", {"_ouid": ouid}, include_deleted=True)

    def find_users_by_match_key(self, match_key: str) -> list[dict[str, Any]]:
        return self.cache_repo.find("employees", {"match_key": match_key}, include_deleted=True)
