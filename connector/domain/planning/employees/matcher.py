from __future__ import annotations

from connector.matcher import MatchResult
from connector.domain.planning.protocols import EmployeeLookup

class EmployeeMatcher:
    """
    Назначение/ответственность:
        Стратегия сопоставления входной записи с текущими пользователями.
    Взаимодействия:
        Дёргает реализацию EmployeeLookup.
    Ограничения:
        Не кеширует результаты, работает синхронно.
    """

    def __init__(self, lookup: EmployeeLookup, include_deleted_users: bool):
        self.lookup = lookup
        self.include_deleted_users = include_deleted_users

    def match(self, match_key: str) -> MatchResult:
        """
        Назначение:
            Найти кандидата в хранилище по match_key.
        Контракт (вход/выход):
            - Вход: match_key: str.
            - Выход: MatchResult со статусом found/not_found/conflict.
        Ошибки/исключения:
            Пробрасывает исключения порта lookup.
        Алгоритм:
            Делегирует в EmployeeLookup.match_by_key.
        """
        return self.lookup.match_by_key(match_key, include_deleted=self.include_deleted_users)
