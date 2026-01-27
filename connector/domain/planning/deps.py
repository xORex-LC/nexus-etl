from __future__ import annotations

from dataclasses import dataclass

from connector.domain.ports.lookups import LookupProtocol


@dataclass
class PlanningDependencies:
    """
    Назначение:
        Объект зависимостей для планировщика конкретного датасета.

    Инварианты:
        - Для employees используется identity_lookup, для других датасетов могут появиться свои поля.
    """

    identity_lookup: LookupProtocol | None = None
