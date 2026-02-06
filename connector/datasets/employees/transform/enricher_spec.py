from __future__ import annotations

from connector.domain.transform.dsl.loader import load_enrich_spec_for_dataset
from connector.domain.transform.dsl.specs import EnrichSpec


def build_employees_enrich_rules(
    enrich_spec: EnrichSpec | None = None,
) -> EnrichSpec:
    """
    Назначение:
        Загрузить Enrich DSL для employees.
    """
    if enrich_spec is None:
        enrich_spec = load_enrich_spec_for_dataset("employees")
    return enrich_spec


def EmployeesEnricherSpec() -> EnrichSpec:
    """
    Назначение:
        Совместимый alias для Enrich DSL employees.
    """
    return build_employees_enrich_rules()
