from __future__ import annotations

from connector.matcher import MatchResult, matchEmployeeByMatchKey
from .protocols import EmployeeLookup

class CacheEmployeeLookup(EmployeeLookup):
    """
    Назначение/ответственность:
        Адаптер порта EmployeeLookup, использующий локальный кэш/БД.
    Взаимодействия:
        Делегирует поиск в matchEmployeeByMatchKey.
    Ограничения:
        Транзакционность/соединение остаются на уровне вызывающего кода.
    """

    def __init__(self, conn):
        self.conn = conn

    def match_by_key(self, match_key: str, include_deleted: bool) -> MatchResult:
        """
        Назначение:
            Поиск пользователя по match_key в кэше.
        Контракт (вход/выход):
            - Вход: match_key: str, include_deleted: bool.
            - Выход: MatchResult (found/not_found/conflict и кандидат).
        Ошибки/исключения:
            Пробрасывает исключения работы с БД.
        Алгоритм:
            Делегирует в matchEmployeeByMatchKey.
        """
        return matchEmployeeByMatchKey(self.conn, match_key, include_deleted)
