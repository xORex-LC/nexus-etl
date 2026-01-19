from __future__ import annotations

from dataclasses import dataclass

from connector.domain.planning.protocols import EmployeeLookup


@dataclass
class PlanningDependencies:
    """
    Назначение:
        Объект зависимостей для планировщика конкретного датасета.

    Инварианты:
        - Для employees используется employee_lookup, для других датасетов могут появиться свои поля.
    """

    employee_lookup: EmployeeLookup | None = None
