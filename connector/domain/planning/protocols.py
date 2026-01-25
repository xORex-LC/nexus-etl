from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from connector.domain.models import Identity, MatchResult, ValidationRowResult, ValidationErrorItem


class PlanDecisionKind(str, Enum):
    """
    Назначение:
        Тип решения планирования по строке.
    """

    CREATE = "create"
    UPDATE = "update"
    SKIP = "skip"
    CONFLICT = "conflict"


@dataclass
class PlanDecision:
    """
    Назначение:
        Унифицированное решение policy по строке.
    Инварианты:
        - Policy не бросает обычных исключений; всё ожидаемое возвращается через PlanDecision.
        - Для create/update обязателен desired_state, changes и resource_id.
    """

    kind: PlanDecisionKind
    identity: Identity
    desired_state: dict[str, Any] | None = None
    changes: dict[str, Any] | None = None
    resource_id: str | None = None
    source_ref: dict[str, Any] | None = None
    secret_fields: list[str] = field(default_factory=list)
    reason_code: str | None = None
    message: str | None = None
    warnings: list[ValidationErrorItem] = field(default_factory=list)


class PlanningPolicyProtocol(Protocol):
    """
    Назначение/ответственность:
        Контракт датасетной политики планирования (вся специфика внутри).
    Взаимодействия:
        Используется GenericPlanner и не содержит IO/infra.
    """

    def decide(self, validated_entity: Any, validation: ValidationRowResult) -> PlanDecision:
        """
        Назначение:
            Вернуть решение по одной валидированной строке.
        Контракт (вход/выход):
            - Вход: validated_entity + ValidationRowResult.
            - Выход: PlanDecision (create/update/skip/conflict).
        Ошибки/исключения:
            Бросает исключения только для фатальных/некорректных входов.
        """
        ...

class IdentityLookup(Protocol):
    """
    Назначение/ответственность:
        Порт для поиска сущности по identity, чтобы планировщик не зависел от конкретного хранилища.
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
