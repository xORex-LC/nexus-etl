from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from connector.domain.models import MatchResult
from connector.planModels import PlanItem


class EntityPlanner(Protocol):
    """
    Назначение/ответственность:
        Общий контракт планировщика сущности (строка -> операция плана).
    Взаимодействия:
        Используется реестром планировщиков и оркестратором планирования.
    """

    def plan_row(self, desired_state, line_no: int, match_key: str) -> "PlanningResult":
        """
        Назначение:
            Решить операцию плана по строке входного набора.
        Контракт:
            Вход: desired_state (dict-like), line_no, match_key.
            Выход: PlanningResult с типом результата и данными.
        """
        ...


class PlanningKind(str, Enum):
    """
    Назначение:
        Тип результата планирования по строке.
    """

    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"
    CONFLICT = "conflict"


@dataclass
class PlanningResult:
    """
    Назначение:
        Результат планирования одной строки.
    Контракт:
        - kind: тип результата (create/update/skip/conflict)
        - item: PlanItem для create/update, иначе None
        - match_result: подробности сопоставления (для аудита/конфликтов)
        - skip_reason: причина skip (опционально)
    """

    kind: PlanningKind
    item: PlanItem | None
    match_result: MatchResult | None = None
    skip_reason: str | None = None

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
