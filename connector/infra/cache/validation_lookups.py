from __future__ import annotations

from connector.domain.ports.lookups import OrgLookupProtocol
from connector.infra.cache import repo

class CacheOrgLookup(OrgLookupProtocol):
    """
    Назначение/ответственность:
        Адаптер org_lookup для валидатора поверх локального кэша.

    Взаимодействия:
        Делегирует чтение в cacheRepo.getOrgByOuid.
    """

    def __init__(self, conn):
        self.conn = conn

    def get_org_by_id(self, ouid: int):
        """
        Контракт:
            Вход: ouid организации.
            Выход: запись организации или None.
        """
        return repo.getOrgByOuid(self.conn, ouid)
    
