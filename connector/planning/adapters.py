from __future__ import annotations

from connector.matcher import MatchResult, matchEmployeeByMatchKey
from .protocols import EmployeeLookup

class CacheEmployeeLookup(EmployeeLookup):
    """
    Назначение/ответственность:
        Адаптер EmployeeLookup, использующий локальный кэш/БД.

    Взаимодействия:
        Делегирует поиск в matchEmployeeByMatchKey.
    """

    def __init__(self, conn):
        self.conn = conn

    def match_by_key(self, match_key: str, include_deleted: bool) -> MatchResult:
        """
        Контракт:
            Вход: match_key, флаг include_deleted.
            Выход: MatchResult.
        """
        return matchEmployeeByMatchKey(self.conn, match_key, include_deleted)
