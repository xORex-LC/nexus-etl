from __future__ import annotations

from connector.domain.planning.employees.decision import EmployeeDecisionPolicy
from connector.domain.planning.employees.differ import EmployeeDiffer
from connector.domain.planning.employees.matcher import EmployeeMatcher
from connector.domain.planning.employees.planner import EmployeePlanner
from connector.domain.planning.protocols import EmployeeLookup, DatasetPlanner

class PlannerRegistry:
    """
    Назначение/ответственность:
        Регистр сущностных планировщиков по имени датасета.
    Взаимодействия:
        Делегирует создание PlannerFactory.
    Ограничения:
        Пока поддерживает только dataset 'employees'.
    """

    def __init__(self, employee_lookup: EmployeeLookup):
        self.employee_lookup = employee_lookup

    def get(self, dataset: str, include_deleted_users: bool) -> DatasetPlanner:
        """
        Назначение:
            Вернуть планировщик нужного датасета.
        Контракт (вход/выход):
            - Вход: dataset: str, include_deleted_users: bool.
            - Выход: экземпляр планировщика сущности.
        Ошибки/исключения:
            ValueError — если датасет не поддерживается.
        Алгоритм:
            Сейчас только employees: собирает matcher/differ/decision.
        """
        if dataset != "employees":
            raise ValueError(f"Unsupported dataset: {dataset}")
        matcher = EmployeeMatcher(self.employee_lookup, include_deleted_users)
        differ = EmployeeDiffer()
        decision = EmployeeDecisionPolicy()
        return EmployeePlanner(matcher=matcher, differ=differ, decision=decision)
