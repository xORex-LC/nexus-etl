from __future__ import annotations

from connector.matcher import MatchResult
from .protocols import EmployeeLookup

class EmployeeMatcher:
    """
    Назначение/ответственность:
        Стратегия сопоставления входной записи с текущими пользователями.

    Взаимодействия:
        Дергает реализацию EmployeeLookup.
    """

    def __init__(self, lookup: EmployeeLookup, include_deleted_users: bool):
        self.lookup = lookup
        self.include_deleted_users = include_deleted_users

    def match(self, match_key: str) -> MatchResult:
        """
        Контракт:
            Вход: match_key строки CSV.
            Выход: MatchResult (found/not_found/conflict).
        Ошибки:
            Пробрасывает исключения lookup.
        Алгоритм:
            Делегирует в порт lookup.
        """
        return self.lookup.match_by_key(match_key, include_deleted=self.include_deleted_users)
