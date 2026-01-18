from __future__ import annotations

from connector.planning.employee_planner import EmployeePlanner
from connector.planning.factory import PlannerFactory

class PlannerRegistry:
    """
    Назначение/ответственность:
        Регистр сущностных планировщиков по имени датасета.
    """

    def __init__(self, factory: PlannerFactory):
        self.factory = factory

    def get(self, dataset: str, include_deleted_users: bool) -> EmployeePlanner:
        """
        Контракт:
            Вход: dataset (пока поддерживается только 'employees'), include_deleted_users.
            Выход: конкретный планировщик сущности.
        Ошибки:
            ValueError при неизвестном датасете.
        """
        if dataset != "employees":
            raise ValueError(f"Unsupported dataset: {dataset}")
        return self.factory.create_employee_planner(include_deleted_users)
