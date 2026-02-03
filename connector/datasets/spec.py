from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol

from connector.domain.diagnostics.catalog import ErrorCatalog

from connector.domain.validation.deps import ValidationDependencies
from connector.domain.validation.validator import Validator
from connector.domain.planning.deps import PlanningDependencies
from connector.domain.planning.rules import LinkRules, MatchingRules, ResolveRules
from connector.domain.ports.execution import RequestSpec, ExecutionResult
from connector.domain.transform.enricher import Enricher
from connector.domain.transform.normalizer import Normalizer
from connector.domain.transform.pipeline import TransformPipeline
from connector.domain.transform.source_record import SourceRecord
from connector.infra.cache.cache_spec import CacheSpec

@dataclass
class ValidationBundle:
    """
    Назначение:
        Валидатор для конкретного датасета.
    """
    validator: Validator


@dataclass(frozen=True)
class PlanningBundle:
    """
    Назначение:
        Набор правил для planning (match/resolve/link).
    """

    matching_rules: MatchingRules
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
        Контракт плагина датасета: валидаторы, проектор, планировщик, отчётные настройки.
    """

    def build_validation_deps(self, conn, settings) -> ValidationDependencies: ...
    def build_planning_deps(self, conn, settings) -> PlanningDependencies: ...
    def build_enrich_deps(self, conn, settings, secret_store=None): ...
    def build_pipeline(
        self,
        deps: ValidationDependencies,
        enrich_deps,
        catalog: ErrorCatalog,
    ) -> TransformPipeline: ...
    def build_validator(self, deps: ValidationDependencies, catalog: ErrorCatalog) -> ValidationBundle: ...
    def build_cache_specs(self) -> list[CacheSpec]: ...
    def build_record_source(
        self,
        csv_path: str,
        csv_has_header: bool,
    ) -> Iterable[SourceRecord]: ...
    def build_planning_bundle(self) -> PlanningBundle: ...
    def get_report_adapter(self) -> ReportAdapter: ...
    def get_apply_adapter(self) -> ApplyAdapter: ...
    def get_diagnostic_catalog(self, strict: bool) -> ErrorCatalog: ...
