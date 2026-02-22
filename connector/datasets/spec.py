"""
Назначение:
    Контракты dataset-плагина для transform/planning/apply сценариев.

    DatasetSpec (Protocol) — narrowed: DSL configuration + adapters.
    build_*_stage() и build_*_deps() удалены из Protocol (DEC-004 Stage 3).
    Сборка стадий — ответственность StageFactory + PipelineContainer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.target.apply import ApplyAdapterProtocol
from connector.domain.transform.core.source_record import SourceRecord
from connector.domain.transform_dsl.specs import (
    EnrichSpec,
    MappingSpec,
    MatchSpec,
    NormalizeSpec,
    ResolveSpec,
    SinkSpec,
)


@dataclass(frozen=True)
class ReportAdapter:
    """
    Назначение:
        Набор констант/лейблов для отчётов по датасету.
    """
    identity_label: str
    conflict_code: str
    conflict_field: str


class DatasetSpec(Protocol):
    """
    Назначение:
        Контракт плагина датасета: DSL configuration + adapters.

    Граница:
        - build_*_spec() — DSL-конфигурация (Phase 1 compromise, see DEC-005).
        - build_record_source() — доступ к источнику данных.
        - get_report_adapter() / get_apply_adapter() — отчётные/apply адаптеры.
        - get_diagnostic_catalog() — каталог ошибок.
        - build_*_stage(), build_*_deps() удалены (DEC-004 Stage 3).
    """

    dataset_name: str

    def build_map_spec(self, settings=None) -> MappingSpec: ...
    def build_normalize_spec(self, settings=None) -> NormalizeSpec: ...
    def build_enrich_spec(self, settings=None) -> EnrichSpec: ...
    def build_match_spec(self, settings=None) -> MatchSpec: ...
    def build_resolve_spec(self, settings=None) -> ResolveSpec: ...
    def build_sink_spec(self, settings=None) -> SinkSpec | None: ...
    def build_record_source(
        self,
        csv_has_header: bool,
    ) -> Iterable[SourceRecord]: ...
    def get_report_adapter(self) -> ReportAdapter: ...
    def get_apply_adapter(self) -> ApplyAdapterProtocol: ...
    def get_diagnostic_catalog(self, strict: bool) -> ErrorCatalog: ...
