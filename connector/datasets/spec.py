"""
Назначение:
    Контракты dataset-плагина для transform/planning/apply сценариев.
"""

from __future__ import annotations

from typing import Any
from dataclasses import dataclass
from typing import Iterable, Protocol

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.secrets.provider import SecretStoreProtocol
from connector.domain.transform_dsl.specs import (
    EnrichSpec,
    MappingSpec,
    MatchSpec,
    NormalizeSpec,
    ResolveSpec,
    SinkSpec,
)
from connector.domain.ports.cache.roles import EnrichLookupPort, PlanningRuntimePort
from connector.domain.ports.transform.dictionaries import DictionaryProviderPort
from connector.domain.transform.providers.deps import TransformProviderDeps
from connector.domain.transform.resolver.resolve_deps import PlanningDependencies
from connector.domain.transform.stages.stages import (
    EnrichStage,
    MapStage,
    MatchStage,
    NormalizeStage,
    ResolveStage,
)
from connector.domain.ports.target.apply import ApplyAdapterProtocol
from connector.domain.transform.core.source_record import SourceRecord


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
        Контракт плагина датасета: transform/planning/apply/report адаптеры.
    """

    dataset_name: str

    def build_planning_deps(self, settings, *, planning_runtime: PlanningRuntimePort) -> PlanningDependencies: ...
    def build_enrich_deps(
        self,
        settings: Any,
        *,
        enrich_lookup: EnrichLookupPort,
        secret_store: SecretStoreProtocol | None = None,
        dictionaries: DictionaryProviderPort | None = None,
    ) -> TransformProviderDeps: ...
    def build_map_spec(self, settings=None) -> MappingSpec: ...
    def build_normalize_spec(self, settings=None) -> NormalizeSpec: ...
    def build_enrich_spec(self, settings=None) -> EnrichSpec: ...
    def build_match_spec(self, settings=None) -> MatchSpec: ...
    def build_resolve_spec(self, settings=None) -> ResolveSpec: ...
    def build_sink_spec(self, settings=None) -> SinkSpec | None: ...
    def build_map_stage(
        self,
        *,
        catalog: ErrorCatalog,
    ) -> MapStage: ...
    def build_normalize_stage(
        self,
        *,
        catalog: ErrorCatalog,
    ) -> NormalizeStage: ...
    def build_enrich_stage(
        self,
        *,
        catalog: ErrorCatalog,
        enrich_deps,
    ) -> EnrichStage: ...
    def build_match_stage(
        self,
        *,
        planning_deps: PlanningDependencies,
        catalog: ErrorCatalog,
        include_deleted: bool,
        settings=None,
    ) -> MatchStage: ...
    def build_resolve_stage(
        self,
        *,
        planning_deps: PlanningDependencies,
        catalog: ErrorCatalog,
        settings=None,
    ) -> ResolveStage: ...
    def build_transform_stages(
        self,
        *,
        enrich_deps,
        catalog: ErrorCatalog,
    ) -> tuple[MapStage, NormalizeStage, EnrichStage]: ...
    def build_planning_stages(
        self,
        *,
        planning_deps: PlanningDependencies,
        catalog: ErrorCatalog,
        include_deleted: bool,
        settings=None,
    ) -> tuple[MatchStage, ResolveStage]: ...
    def build_record_source(
        self,
        csv_has_header: bool,
    ) -> Iterable[SourceRecord]: ...
    def get_report_adapter(self) -> ReportAdapter: ...
    def get_apply_adapter(self) -> ApplyAdapterProtocol: ...
    def get_diagnostic_catalog(self, strict: bool) -> ErrorCatalog: ...
