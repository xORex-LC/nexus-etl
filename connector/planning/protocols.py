from __future__ import annotations

from typing import Protocol

from connector.matcher import MatchResult
from connector.planModels import PlanItem


class EntityPlanner(Protocol):
    """
    Назначение/ответственность:
        Общий контракт планировщика сущности (строка -> операция плана).
    Взаимодействия:
        Используется реестром планировщиков и оркестратором планирования.
    """

    def plan_row(self, desired_state, line_no: int, match_key: str) -> tuple[str, PlanItem | None, MatchResult | None]:
        """
        Назначение:
            Решить операцию плана по строке входного набора.
        Контракт:
            Вход: desired_state (dict-like), line_no, match_key.
            Выход: (status, plan_item|None, match_result|None), где status: create/update/skip/conflict.
        """
        ...

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
