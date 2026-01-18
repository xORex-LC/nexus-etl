from __future__ import annotations

from connector.domain.planning.employees.planner import EmployeePlanner
from connector.domain.planning.factory import PlannerFactory
from connector.domain.planning.protocols import EntityPlanner

class PlannerRegistry:
    """
    Назначение/ответственность:
        Регистр сущностных планировщиков по имени датасета.
    Взаимодействия:
        Делегирует создание PlannerFactory.
    Ограничения:
        Пока поддерживает только dataset 'employees'.
    """

    def __init__(self, factory: PlannerFactory):
        self.factory = factory

    def get(self, dataset: str, include_deleted_users: bool) -> EntityPlanner:
        """
        Назначение:
            Вернуть планировщик нужного датасета.
        Контракт (вход/выход):
            - Вход: dataset: str, include_deleted_users: bool.
            - Выход: экземпляр планировщика сущности.
        Ошибки/исключения:
            ValueError — если датасет не поддерживается.
        Алгоритм:
            Сейчас только employees -> factory.create_employee_planner.
        """
        if dataset != "employees":
            raise ValueError(f"Unsupported dataset: {dataset}")
        return self.factory.create_employee_planner(include_deleted_users)
