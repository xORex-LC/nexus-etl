from __future__ import annotations

from connector.datasets.spec import DatasetSpec, ValidatorBundle
from connector.datasets.employees.projector import EmployeesProjector
from connector.datasets.employees.reporting import employees_report_adapter
from connector.domain.planning.adapters import CacheEmployeeLookup
from connector.datasets.planning.registry import PlannerRegistry
from connector.domain.validation.deps import ValidationDependencies
from connector.datasets.validation.registry import ValidatorRegistry

class EmployeesSpec(DatasetSpec):
    """
    DatasetSpec для employees: собирает валидаторы, проектор, планировщик и отчётные настройки.
    """

    def __init__(self, conn):
        self.conn = conn
        self._projector = EmployeesProjector()
        self._report_adapter = employees_report_adapter

    def build_validators(self, deps: ValidationDependencies) -> ValidatorBundle:
        registry = ValidatorRegistry(deps)
        row_validator = registry.create_row_validator("employees")
        state = registry.create_state()
        dataset_validator = registry.create_dataset_validator("employees", state)
        return ValidatorBundle(row_validator=row_validator, dataset_validator=dataset_validator, state=state)

    def get_projector(self):
        return self._projector

    def build_planner(self, include_deleted_users: bool):
        registry = PlannerRegistry(employee_lookup=CacheEmployeeLookup(self.conn))
        return registry.get(dataset="employees", include_deleted_users=include_deleted_users)

    def get_report_adapter(self):
        return self._report_adapter

# Фабрика экземпляра спеки (conn нужен для lookup/валидаторов)
def make_employees_spec(conn) -> EmployeesSpec:
    return EmployeesSpec(conn)
