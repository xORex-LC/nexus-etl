"""
Назначение:
    DatasetSpec-реализация для employees.

Граница ответственности:
    - Owns: DSL spec loaders, record source, report/apply adapters.
    - Does NOT: собирать стадии (DEC-004: StageFactory + PipelineContainer).
"""

from __future__ import annotations

from typing import Any

from connector.datasets.apply_adapter import OperationApplyAdapter
from connector.datasets.spec import (
    DatasetSpec,
    ReportAdapter,
)
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.planning.plan_models import PlanItem
from connector.domain.transform_dsl import (
    load_enrich_spec_for_dataset,
    load_mapping_spec_for_dataset,
    load_match_spec_for_dataset,
    load_normalize_spec_for_dataset,
    load_resolve_spec_for_dataset,
    load_sink_spec_for_dataset,
    load_source_spec_for_dataset,
    resolve_source_location,
)
from connector.domain.transform_dsl.specs import (
    EnrichSpec,
    MappingSpec,
    MatchSpec,
    NormalizeSpec,
    ResolveSpec,
    SinkSpec,
)
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow
from connector.infra.sources.csv_reader import CsvRecordSource
from connector.infra.target.providers.ankey_rest.payloads import (
    build_user_upsert_payload,
)
from connector.datasets.employees.diagnostic_catalog import build_employees_catalog

class EmployeesSpec(DatasetSpec):
    """
    Назначение:
        DatasetSpec для employees: DSL specs, record source, report/apply adapters.
    """

    row_builder = NormalizedEmployeesRow

    def __init__(
        self,
        secrets: SecretProviderProtocol | None = None,
        *,
        dataset_name: str = "employees",
    ):
        self.dataset_name = dataset_name
        self._report_adapter = ReportAdapter(
            identity_label="match_key",
            conflict_code="MATCH_CONFLICT",
            conflict_field="matchKey",
        )
        self._apply_adapter = OperationApplyAdapter(
            operation_alias="users.upsert",
            payload_builder=build_user_upsert_payload,
            dataset=self.dataset_name,
            params_builder=_build_employees_operation_params,
            secrets=secrets,
        )

    # ── DSL spec builders (Protocol-required) ─────────────────────────────────

    def build_map_spec(self, settings=None) -> MappingSpec:
        _ = settings
        return load_mapping_spec_for_dataset(self.dataset_name)

    def build_normalize_spec(self, settings=None) -> NormalizeSpec:
        _ = settings
        return load_normalize_spec_for_dataset(self.dataset_name)

    def build_enrich_spec(self, settings=None) -> EnrichSpec:
        _ = settings
        return load_enrich_spec_for_dataset(self.dataset_name)

    def build_match_spec(self, settings=None) -> MatchSpec:
        _ = settings
        return load_match_spec_for_dataset(self.dataset_name)

    def build_resolve_spec(self, settings=None) -> ResolveSpec:
        _ = settings
        return load_resolve_spec_for_dataset(self.dataset_name)

    def build_sink_spec(self, settings=None) -> SinkSpec:
        _ = settings
        return load_sink_spec_for_dataset(self.dataset_name)

    # ── Record source & adapters (Protocol-required) ──────────────────────────

    def build_record_source(
        self,
        csv_has_header: bool,
    ):
        source_spec = load_source_spec_for_dataset(self.dataset_name)
        if source_spec.source.type != "file" or source_spec.source.format != "csv":
            raise ValueError("employees source spec must be file/csv for current runtime")
        source_path = resolve_source_location(source_spec)
        return CsvRecordSource(source_path, csv_has_header)

    def get_report_adapter(self):
        return self._report_adapter

    def get_apply_adapter(self):
        return self._apply_adapter

    def get_diagnostic_catalog(self, strict: bool):
        return build_employees_catalog(strict=strict)


# Фабрика экземпляра спеки
def make_employees_spec(secrets: SecretProviderProtocol | None = None) -> EmployeesSpec:
    return EmployeesSpec(secrets=secrets, dataset_name="employees")



def _build_employees_operation_params(item: PlanItem) -> dict[str, Any]:
    target_id = item.target_id
    if target_id is None:
        raise ValueError("target_id is required for operation users.upsert")
    normalized = str(target_id).strip()
    if normalized == "":
        raise ValueError("target_id is required for operation users.upsert")
    return {"target_id": normalized}
