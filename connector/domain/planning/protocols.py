from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from connector.domain.models import Identity, MatchResult
from connector.planModels import PlanItem


class DatasetPlanner(Protocol):
    """
    Назначение/ответственность:
        Общий контракт планировщика датасета (строка -> операция плана).
    Взаимодействия:
        Используется реестром планировщиков и оркестратором планирования.
    """

    def plan_row(self, desired_state, line_no: int, identity: Identity) -> "PlanningResult":
        """
        Назначение:
            Решить операцию плана по строке входного набора.
        Контракт:
            Вход: desired_state (dict-like), line_no, identity.
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
        Порт для поиска сотрудников по identity, чтобы планировщик не зависел от конкретного хранилища.
    Взаимодействия:
        Вызывается планировщиком; реализации обращаются к кэшу/БД/API.
    Ограничения:
        Синхронный вызов, без внутреннего кеширования.
    """

    def match(self, identity: Identity, include_deleted: bool) -> MatchResult:
        """
        Назначение:
            Найти кандидатов по primary identity с учётом удалённых пользователей.
        Контракт (вход/выход):
            - Вход: identity: Identity, include_deleted: bool — учитывать ли удалённых.
            - Выход: MatchResult (status not_found/found/conflict и кандидат).
        Ошибки/исключения:
            Реализация может пробрасывать ошибки транспорта/БД.
        Алгоритм:
            Определяется реализацией порта.
        """
        ...
