from __future__ import annotations

from connector.planning.decision import EmployeeDecisionPolicy
from connector.planning.differ import EmployeeDiffer
from connector.planning.employee_planner import EmployeePlanner
from connector.planning.matcher import EmployeeMatcher
from connector.planning.protocols import EmployeeLookup

class PlannerFactory:
    """
    Назначение/ответственность:
        Сборка планировщиков для разных датасетов.

    Взаимодействия:
        Принимает адаптеры lookup и возвращает готовые сущностные планировщики.
    """

    def __init__(self, employee_lookup: EmployeeLookup):
        self.employee_lookup = employee_lookup

    def create_employee_planner(self, include_deleted_users: bool) -> EmployeePlanner:
        """
        Контракт:
            Вход: флаг include_deleted_users.
            Выход: EmployeePlanner.
        """
        matcher = EmployeeMatcher(self.employee_lookup, include_deleted_users)
        differ = EmployeeDiffer()
        decision = EmployeeDecisionPolicy()
        return EmployeePlanner(matcher=matcher, differ=differ, decision=decision)
