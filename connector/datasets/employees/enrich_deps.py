from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from connector.domain.ports.lookups import LookupProtocol
from connector.domain.ports.secrets import SecretStoreProtocol
from connector.infra.cache import legacy_queries


@dataclass(frozen=True)
class EmployeesEnrichDependencies:
    """
    Назначение:
        Набор зависимостей enrich для employees.
    """

    conn: Any
    identity_lookup: LookupProtocol | None
    secret_store: SecretStoreProtocol | None = None

    def find_user_by_id(self, resource_id: str) -> dict[str, Any] | None:
        return legacy_queries.findUserById(self.conn, resource_id)

    def find_user_by_usr_org_tab_num(self, tab_num: str) -> dict[str, Any] | None:
        return legacy_queries.findUserByUsrOrgTabNum(self.conn, tab_num)
