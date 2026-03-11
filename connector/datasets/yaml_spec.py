"""
Назначение:
    Generic YAML-driven DatasetSpec implementation.

Граница ответственности:
    - Owns: сборка DatasetSpec из YAML-конфигурации (registry.yml + stage YAML files).
    - Does NOT: загрузка registry.yml (dataset_dsl.loader), компиляция payload (dataset_dsl.payload_compiler).
"""

from __future__ import annotations

from typing import Iterable

from connector.datasets.apply_adapter import OperationApplyAdapter
from connector.datasets.spec import ReportAdapter, UnsupportedStageError
from connector.domain.dataset_dsl.catalog_compiler import compile_diagnostic_catalog
from connector.domain.dataset_dsl.params_compiler import resolve_params_builder
from connector.domain.dataset_dsl.payload_compiler import SinkDrivenPayloadBuilder
from connector.domain.dataset_dsl.specs import DatasetDslSpec
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.ports.target.apply import ApplyAdapterProtocol
from connector.domain.transform.core.source_record import SourceRecord
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
from connector.infra.sources.csv_reader import CsvRecordSource

_STAGE_LOADERS = {
    "map": load_mapping_spec_for_dataset,
    "normalize": load_normalize_spec_for_dataset,
    "enrich": load_enrich_spec_for_dataset,
    "match": load_match_spec_for_dataset,
    "resolve": load_resolve_spec_for_dataset,
    "sink": load_sink_spec_for_dataset,
}


class YamlDatasetSpec:
    """
    Назначение:
        Generic DatasetSpec, построенный полностью из YAML-конфигурации.
        Заменяет хардкодированные per-dataset реализации (EmployeesSpec).

    Контракт:
        - build_spec_for(stage_type) — generic accessor для DSL spec любой стадии.
        - build_record_source() — источник записей (CSV).
        - get_report_adapter() — report adapter из registry.yml.
        - get_apply_adapter() — apply adapter с SinkSpec-driven payload builder.
        - get_diagnostic_catalog() — diagnostic catalog из registry.yml.
    """

    def __init__(
        self,
        dataset_name: str,
        dsl_spec: DatasetDslSpec,
        secrets: SecretProviderProtocol | None = None,
    ) -> None:
        self.dataset_name = dataset_name
        self._dsl_spec = dsl_spec
        self._secrets = secrets

    def build_spec_for(self, stage_type: str) -> object:
        """
        Назначение:
            Загрузить DSL-спецификацию для стадии по ключу.

        Raises:
            UnsupportedStageError: если стадия не поддерживается.
        """
        loader = _STAGE_LOADERS.get(stage_type)
        if loader is None:
            raise UnsupportedStageError(stage_type, dataset=self.dataset_name)
        return loader(self.dataset_name)

    def build_record_source(self) -> Iterable[SourceRecord]:
        source_spec = load_source_spec_for_dataset(self.dataset_name)
        if source_spec.source.type != "file" or source_spec.source.format != "csv":
            raise ValueError(
                f"{self.dataset_name} source spec must be file/csv for current runtime"
            )
        source_path = resolve_source_location(source_spec)
        return CsvRecordSource(source_path, source_spec.source.has_header)

    def get_report_adapter(self) -> ReportAdapter:
        r = self._dsl_spec.report
        return ReportAdapter(
            identity_label=r.identity_label,
            conflict_code=r.conflict_code,
            conflict_field=r.conflict_field,
        )

    def get_apply_adapter(self) -> ApplyAdapterProtocol:
        sink_spec = load_sink_spec_for_dataset(self.dataset_name)
        apply = self._dsl_spec.apply
        payload_builder = SinkDrivenPayloadBuilder(
            sink_spec=sink_spec,
            defaults=dict(apply.payload.defaults),
            conditional_fields=list(apply.payload.conditional_fields),
        )
        params_builder = resolve_params_builder(apply.params)
        return OperationApplyAdapter(
            operation_alias=apply.operation_alias,
            payload_builder=payload_builder,
            dataset=self.dataset_name,
            params_builder=params_builder,
            secrets=self._secrets,
        )

    def get_diagnostic_catalog(self, strict: bool) -> ErrorCatalog:
        return compile_diagnostic_catalog(
            self._dsl_spec.diagnostics,
            strict=strict,
        )
