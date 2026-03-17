"""Назначение:
    Runtime accessor для уже загруженного YAML-driven DatasetSpec.

Граница ответственности:
    - Owns: доступ к preloaded dataset snapshot и сборку runtime adapters.
    - Does NOT: чтение YAML-файлов, eager validation registry и выбор dataset factory.
"""

from __future__ import annotations

from typing import Iterable

from connector.datasets.apply_adapter import OperationApplyAdapter
from connector.datasets.spec import ReportAdapter, UnsupportedStageError
from connector.datasets.yaml_spec_loader import LoadedYamlDatasetArtifacts
from connector.domain.dataset_dsl.catalog_compiler import compile_diagnostic_catalog
from connector.domain.dataset_dsl.params_compiler import resolve_params_builder
from connector.domain.dataset_dsl.payload_compiler import SinkDrivenPayloadBuilder
from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.ports.target.apply import ApplyAdapterProtocol
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform_dsl import resolve_source_location
from connector.infra.sources.csv_reader import CsvRecordSource


class YamlDatasetSpec:
    """Назначение:
        Generic DatasetSpec поверх preloaded YAML snapshot.

    Контракт:
        - `build_spec_for()` не делает I/O и возвращает изолированную копию spec;
        - `build_record_source()` использует только preloaded `SourceSpec`;
        - `get_apply_adapter()` использует только preloaded `SinkSpec` и dataset DSL.
    """

    def __init__(
        self,
        artifacts: LoadedYamlDatasetArtifacts,
        secrets: SecretProviderProtocol | None = None,
    ) -> None:
        self.dataset_name = artifacts.dataset_name
        self._artifacts = artifacts
        self._secrets = secrets

    def build_spec_for(self, stage_type: str) -> object:
        """Назначение:
            Вернуть preloaded stage spec по ключу без повторной загрузки YAML.

        Контракт:
            - unknown stage → `UnsupportedStageError`;
            - каждая выдача изолирована через `model_copy(deep=True)`.
        """
        stage_spec = self._artifacts.stage_specs.get(stage_type)
        if stage_spec is None:
            raise UnsupportedStageError(stage_type, dataset=self.dataset_name)
        return stage_spec.model_copy(deep=True)

    def build_record_source(self) -> Iterable[SourceRecord]:
        """Назначение:
            Построить record source из preloaded source spec.

        Контракт:
            - не читает source YAML повторно;
            - path resolution выполняется runtime-safe через `location_ref/location`.
        """
        source_spec = self._artifacts.source_spec
        if source_spec.source.type != "file" or source_spec.source.format != "csv":
            raise ValueError(
                f"{self.dataset_name} source spec must be file/csv for current runtime"
            )
        source_path = resolve_source_location(source_spec)
        return CsvRecordSource(source_path, source_spec.source.has_header)

    def get_report_adapter(self) -> ReportAdapter:
        r = self._artifacts.dataset_dsl.report
        return ReportAdapter(
            identity_label=r.identity_label,
            conflict_code=r.conflict_code,
            conflict_field=r.conflict_field,
        )

    def get_apply_adapter(self) -> ApplyAdapterProtocol:
        """Назначение:
            Собрать apply adapter поверх preloaded sink spec и dataset DSL.

        Контракт:
            - не читает sink YAML повторно;
            - каждый вызов создаёт новый adapter instance.
        """
        sink_spec = self._artifacts.sink_spec
        apply = self._artifacts.dataset_dsl.apply
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
            self._artifacts.dataset_dsl.diagnostics,
            strict=strict,
        )
