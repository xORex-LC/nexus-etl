from __future__ import annotations

from connector.datasets.spec import DatasetSpec, ValidatorBundle
from connector.datasets.employees.projector import EmployeesProjector
from connector.datasets.employees.reporting import employees_report_adapter
from connector.datasets.employees.apply_adapter import EmployeesApplyAdapter
from connector.domain.planning.adapters import CacheEmployeeLookup
from connector.domain.planning.deps import PlanningDependencies
from connector.domain.planning.employees.decision import EmployeeDecisionPolicy
from connector.domain.planning.employees.differ import EmployeeDiffer
from connector.domain.planning.employees.matcher import EmployeeMatcher
from connector.datasets.employees.planning_policy import EmployeesPlanningPolicy
from connector.domain.validation.deps import ValidationDependencies
from connector.datasets.validation.registry import ValidatorRegistry
from connector.infra.cache.validation_lookups import CacheOrgLookup
from connector.domain.ports.secrets import SecretProviderProtocol

class EmployeesSpec(DatasetSpec):
    """
    DatasetSpec для employees: собирает валидаторы, проектор, планировщик и отчётные настройки.
    """

    def __init__(self, secrets: SecretProviderProtocol | None = None):
        self._projector = EmployeesProjector()
        self._report_adapter = employees_report_adapter
        self._apply_adapter = EmployeesApplyAdapter(secrets=secrets)

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

    def build_planning_policy(self, include_deleted_users: bool, deps: PlanningDependencies):
        matcher = EmployeeMatcher(deps.employee_lookup, include_deleted_users)
        differ = EmployeeDiffer()
        decision = EmployeeDecisionPolicy()
        return EmployeesPlanningPolicy(
            projector=self._projector,
            matcher=matcher,
            differ=differ,
            decision=decision,
        )

    def get_report_adapter(self):
        return self._report_adapter

    def get_apply_adapter(self):
        return self._apply_adapter

# Фабрика экземпляра спеки
def make_employees_spec(secrets: SecretProviderProtocol | None = None) -> EmployeesSpec:
    return EmployeesSpec(secrets=secrets)
