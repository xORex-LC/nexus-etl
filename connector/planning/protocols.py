from __future__ import annotations

from typing import Protocol

from connector.matcher import MatchResult

class EmployeeLookup(Protocol):
    """
    Назначение/ответственность:
        Порт для поиска сотрудников по match_key.

    Взаимодействия:
        Реализации обращаются к кэшу/БД или API.

    Ограничения:
        Синхронный вызов, не кеширует результаты.
    """

    def match_by_key(self, match_key: str, include_deleted: bool) -> MatchResult:
        """
        Контракт:
            Вход: match_key, include_deleted — учитывать ли удалённых.
            Выход: MatchResult (not_found/found/conflict и кандидат).
        Ошибки:
            Исключения транспорта/БД пробрасываются реализацией.
        """
        ...
