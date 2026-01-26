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
from connector.datasets.employees.source_mapper import EmployeesSourceMapper
from connector.datasets.employees.mapping_spec import EmployeesMappingSpec
from connector.datasets.employees.normalizer_spec import EmployeesNormalizerSpec
from connector.domain.transform.normalizer import Normalizer
from connector.datasets.employees.record_sources import (
    NormalizedEmployeesCsvRecordSource,
    SourceEmployeesCsvRecordSource,
)

class EmployeesSpec(DatasetSpec):
    """
    DatasetSpec для employees: собирает валидаторы, проектор, планировщик и отчётные настройки.
    """

    def __init__(self, secrets: SecretProviderProtocol | None = None):
        self._report_adapter = employees_report_adapter
        self._apply_adapter = EmployeesApplyAdapter(secrets=secrets)

    def build_validation_deps(self, conn, settings) -> ValidationDependencies:
        return ValidationDependencies(org_lookup=CacheOrgLookup(conn))

    def build_planning_deps(self, conn, settings) -> PlanningDependencies:
        return PlanningDependencies(identity_lookup=CacheEmployeeLookup(conn))

    def build_validators(self, deps: ValidationDependencies) -> ValidatorBundle:
        mapping_spec = EmployeesMappingSpec()
        normalizer = Normalizer(EmployeesNormalizerSpec())
        mapper = EmployeesSourceMapper(mapping_spec)
        registry = ValidatorRegistry(deps, normalizer, mapper, mapping_spec.required_fields)
        row_validator = registry.create_row_validator()
        state = registry.create_state()
        dataset_validator = registry.create_dataset_validator(state)
        return ValidatorBundle(row_validator=row_validator, dataset_validator=dataset_validator, state=state)

    def build_record_source(
        self,
        csv_path: str,
        csv_has_header: bool,
        source_format: str | None = None,
    ):
        if source_format == "source":
            return SourceEmployeesCsvRecordSource(csv_path, csv_has_header)
        return NormalizedEmployeesCsvRecordSource(csv_path, csv_has_header)

    def build_planning_policy(self, include_deleted: bool, deps: PlanningDependencies):
        projector = EmployeesProjector()
        matcher = EmployeeMatcher(deps.identity_lookup, include_deleted)
        differ = EmployeeDiffer()
        decision = EmployeeDecisionPolicy()
        return EmployeesPlanningPolicy(
            projector=projector,
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
