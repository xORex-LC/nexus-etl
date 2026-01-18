from __future__ import annotations

from connector.domain.planning.employees.decision import EmployeeDecisionPolicy
from connector.domain.planning.employees.differ import EmployeeDiffer
from connector.domain.planning.employees.planner import EmployeePlanner
from connector.domain.planning.employees.matcher import EmployeeMatcher
from connector.domain.planning.protocols import EmployeeLookup

class PlannerFactory:
    """
    Назначение/ответственность:
        Сборка планировщиков для разных датасетов (сейчас только employees).
    Взаимодействия:
        Принимает адаптеры lookup и возвращает сущностные планировщики.
    Ограничения:
        Stateless: не кеширует созданные экземпляры.
    """

    def __init__(self, employee_lookup: EmployeeLookup):
        self.employee_lookup = employee_lookup

    def create_employee_planner(self, include_deleted_users: bool) -> EmployeePlanner:
        """
        Назначение:
            Сконструировать планировщик сотрудников под заданный флаг include_deleted_users.
        Контракт (вход/выход):
            - Вход: include_deleted_users: bool.
            - Выход: EmployeePlanner.
        Ошибки/исключения:
            Пробрасывает исключения из зависимостей при инициализации.
        Алгоритм:
            Создаёт matcher/differ/decision и собирает EmployeePlanner.
        """
        matcher = EmployeeMatcher(self.employee_lookup, include_deleted_users)
        differ = EmployeeDiffer()
        decision = EmployeeDecisionPolicy()
        return EmployeePlanner(matcher=matcher, differ=differ, decision=decision)
