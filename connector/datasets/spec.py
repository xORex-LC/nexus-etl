from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.transform.dsl.specs import MatchSpec

from connector.domain.transform.matching.resolve_deps import PlanningDependencies
from connector.domain.transform.matching.rules import LinkRules, ResolveRules
from connector.domain.ports.target.execution import RequestSpec, ExecutionResult
from connector.domain.transform.stages.stages import MapStage, NormalizeStage, EnrichStage
from connector.domain.transform.core.source_record import SourceRecord
from connector.infra.cache.cache_spec import CacheSpec

@dataclass(frozen=True)
class PlanningBundle:
    """
    Назначение:
        Набор правил для planning (match/resolve/link).
    """

    match_spec: MatchSpec
    resolve_rules: ResolveRules
    link_rules: LinkRules

class ApplyAdapter(Protocol):
    """
    Назначение:
        Преобразует плановую операцию в спецификацию запроса на исполнение.
    Взаимодействия:
        Используется на слое apply для получения RequestSpec из PlanItem.
    """

    def to_request(self, item) -> RequestSpec: ...

    def on_failed_request(self, item, result: ExecutionResult, retries_left: int):
        """
        Назначение:
            Опционально предложить повторную попытку с модификацией PlanItem.
        Контракт:
            - Вернуть новый PlanItem для ретрая или None, чтобы прекратить попытки.
        """
        ...

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

    def build_planning_deps(self, conn, settings) -> PlanningDependencies: ...
    def build_enrich_deps(self, conn, settings, secret_store=None): ...
    def build_transform_stages(
        self,
        enrich_deps,
        catalog: ErrorCatalog,
    ) -> tuple[MapStage, NormalizeStage, EnrichStage]: ...
    def build_cache_specs(self) -> list[CacheSpec]: ...
    def build_record_source(
        self,
        csv_has_header: bool,
    ) -> Iterable[SourceRecord]: ...
    def build_planning_bundle(self, settings=None) -> PlanningBundle: ...
    def get_report_adapter(self) -> ReportAdapter: ...
    def get_apply_adapter(self) -> ApplyAdapter: ...
    def get_diagnostic_catalog(self, strict: bool) -> ErrorCatalog: ...
