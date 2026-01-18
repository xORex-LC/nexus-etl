from __future__ import annotations

from typing import Protocol

from connector.matcher import MatchResult

class EmployeeLookup(Protocol):
    """
    Назначение/ответственность:
        Порт для поиска сотрудников по match_key, чтобы планировщик не зависел от конкретного хранилища.
    Взаимодействия:
        Вызывается планировщиком; реализации обращаются к кэшу/БД/API.
    Ограничения:
        Синхронный вызов, без внутреннего кеширования.
    """

    def match_by_key(self, match_key: str, include_deleted: bool) -> MatchResult:
        """
        Назначение:
            Найти кандидатов по match_key с учётом удалённых пользователей.
        Контракт (вход/выход):
            - Вход: match_key: str, include_deleted: bool — учитывать ли удалённых.
            - Выход: MatchResult (status not_found/found/conflict и кандидат).
        Ошибки/исключения:
            Реализация может пробрасывать ошибки транспорта/БД.
        Алгоритм:
            Определяется реализацией порта.
        """
        ...
