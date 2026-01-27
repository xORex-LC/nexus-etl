from __future__ import annotations

from connector.domain.ports.lookups import LookupProtocol
from connector.infra.cache import legacy_queries

class CacheOrgLookup(LookupProtocol):
    """
    Назначение/ответственность:
        Адаптер org_lookup для валидатора поверх локального кэша.

    Взаимодействия:
        Делегирует чтение в cacheRepo.getOrgByOuid.
    """

    def __init__(self, conn):
        self.conn = conn

    def get_by_id(self, entity: str, value: int):
        """
        Контракт:
            Вход: ouid организации.
            Выход: запись организации или None.
        """
        if entity not in ("organizations", "orgs"):
            return None
        return legacy_queries.getOrgByOuid(self.conn, int(value))

    def match(self, identity, include_deleted: bool):
        """
        Назначение:
            Для org lookup не поддерживается.
        """
        raise NotImplementedError("Org lookup does not support match()")
    
