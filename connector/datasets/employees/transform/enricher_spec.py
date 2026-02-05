from __future__ import annotations

from connector.domain.transform.enrich import EnricherSpec
from connector.domain.transform.enrich import build_enricher_spec_from_dsl, EnrichDslBuildOptions
from connector.domain.transform.dsl.loader import load_enrich_spec_for_dataset
from connector.domain.transform.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.transform.dsl.specs import EnrichSpec
from connector.datasets.employees.transform.enrich_deps import EmployeesEnrichDependencies
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow


def build_employees_enricher_spec(
    enrich_spec: EnrichSpec | None = None,
) -> EnricherSpec[NormalizedEmployeesRow, EmployeesEnrichDependencies]:
    """
    Назначение:
        Построить EnricherSpec для employees из DSL.
    """
    if enrich_spec is None:
        enrich_spec = load_enrich_spec_for_dataset("employees")
    registry = OperationRegistry()
    register_core_ops(registry)
    return build_enricher_spec_from_dsl(
        enrich_spec,
        registry=registry,
        options=EnrichDslBuildOptions(require_match_key=True),
    )


def EmployeesEnricherSpec() -> EnricherSpec[NormalizedEmployeesRow, EmployeesEnrichDependencies]:
    """
    Назначение:
        Совместимый alias для построения EnricherSpec employees.
    """
    return build_employees_enricher_spec()
