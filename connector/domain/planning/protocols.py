from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from connector.domain.models import Identity, ValidationRowResult, ValidationErrorItem


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
