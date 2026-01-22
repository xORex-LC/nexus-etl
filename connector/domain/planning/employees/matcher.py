from __future__ import annotations

from connector.domain.models import Identity, MatchResult
from connector.domain.planning.protocols import IdentityLookup

class EmployeeMatcher:
    """
    Назначение/ответственность:
        Стратегия сопоставления входной записи с текущими пользователями.
    Взаимодействия:
        Дёргает реализацию IdentityLookup.
    Ограничения:
        Не кеширует результаты, работает синхронно.
    """

    def __init__(self, lookup: IdentityLookup, include_deleted_users: bool):
        self.lookup = lookup
        self.include_deleted_users = include_deleted_users

    def match(self, identity: Identity) -> MatchResult:
        """
        Назначение:
            Найти кандидата в хранилище по identity.
        Контракт (вход/выход):
            - Вход: identity: Identity.
            - Выход: MatchResult со статусом found/not_found/conflict.
        Ошибки/исключения:
            Пробрасывает исключения порта lookup.
        Алгоритм:
            Делегирует в IdentityLookup.match.
        """
        return self.lookup.match(identity, include_deleted=self.include_deleted_users)
