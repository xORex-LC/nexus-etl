from __future__ import annotations

from connector.datasets.spec import DatasetSpec, ValidatorBundle
from connector.datasets.employees.projector import EmployeesProjector
from connector.datasets.employees.reporting import employees_report_adapter
from connector.domain.planning.adapters import CacheEmployeeLookup
from connector.domain.planning.deps import PlanningDependencies
from connector.domain.validation.deps import ValidationDependencies
from connector.datasets.planning.registry import PlannerRegistry
from connector.datasets.validation.registry import ValidatorRegistry
from connector.infra.cache.validation_lookups import CacheOrgLookup

class EmployeesSpec(DatasetSpec):
    """
    DatasetSpec для employees: собирает валидаторы, проектор, планировщик и отчётные настройки.
    """

    def __init__(self):
        self._projector = EmployeesProjector()
        self._report_adapter = employees_report_adapter

    def build_validation_deps(self, conn, settings) -> ValidationDependencies:
        return ValidationDependencies(org_lookup=CacheOrgLookup(conn))

    def build_planning_deps(self, conn, settings) -> PlanningDependencies:
        return PlanningDependencies(employee_lookup=CacheEmployeeLookup(conn))

    def build_validators(self, deps: ValidationDependencies) -> ValidatorBundle:
        registry = ValidatorRegistry(deps)
        row_validator = registry.create_row_validator("employees")
        state = registry.create_state()
        dataset_validator = registry.create_dataset_validator("employees", state)
        return ValidatorBundle(row_validator=row_validator, dataset_validator=dataset_validator, state=state)

    def get_projector(self):
        return self._projector

    def build_planner(self, include_deleted_users: bool, deps: PlanningDependencies):
        registry = PlannerRegistry(employee_lookup=deps.employee_lookup)
        return registry.get(dataset="employees", include_deleted_users=include_deleted_users)

    def get_report_adapter(self):
        return self._report_adapter

# Фабрика экземпляра спеки
def make_employees_spec() -> EmployeesSpec:
    return EmployeesSpec()
