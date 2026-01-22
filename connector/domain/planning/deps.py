from __future__ import annotations

from dataclasses import dataclass

from connector.domain.planning.protocols import IdentityLookup


@dataclass
class PlanningDependencies:
    """
    Назначение:
        Объект зависимостей для планировщика конкретного датасета.

    Инварианты:
        - Для employees используется identity_lookup, для других датасетов могут появиться свои поля.
    """

    identity_lookup: IdentityLookup | None = None
