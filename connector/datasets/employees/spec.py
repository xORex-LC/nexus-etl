from __future__ import annotations

from connector.datasets.spec import DatasetSpec, PlanningBundle
from connector.datasets.employees.load.reporting import employees_report_adapter
from connector.datasets.employees.load.apply_adapter import EmployeesApplyAdapter
from connector.domain.transform.matching.resolve_deps import PlanningDependencies, ResolverSettings
from connector.datasets.employees.load.matching_rules import build_matching_rules
from connector.datasets.employees.load.link_rules import build_link_rules
from connector.datasets.employees.load.resolve_rules import build_resolve_rules
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.transform.mapping import MapperEngine
from connector.domain.transform.dsl.loader import (
    load_normalize_spec_for_dataset,
    load_source_spec_for_dataset,
    resolve_source_location,
)
from connector.domain.transform.dsl.registry import OperationRegistry, register_core_ops
from connector.datasets.employees.transform.normalized import NormalizedEmployeesRow
from connector.datasets.employees.transform.enricher_spec import EmployeesEnricherSpec
from connector.datasets.employees.transform.enrich_deps import EmployeesEnrichDependencies
from connector.domain.transform.enrich import EnricherEngine, EnrichDslBuildOptions
from connector.domain.transform.normalize import NormalizerDsl, NormalizerEngine
from connector.domain.transform.stages.stages import MapStage, NormalizeStage, EnrichStage
from connector.infra.sources.csv_reader import CsvRecordSource
from connector.datasets.employees.load.cache_spec import employees_cache_spec
from connector.datasets.organizations.load.cache_spec import organizations_cache_spec
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.cache.repository import SqliteCacheRepository
from connector.infra.cache.identity_repository import SqliteIdentityRepository
from connector.infra.cache.pending_links_repository import SqlitePendingLinksRepository
from connector.datasets.employees.diagnostic_catalog import build_employees_catalog
from connector.domain.diagnostics.catalog import ErrorCatalog

class EmployeesSpec(DatasetSpec):
    """
    DatasetSpec для employees: собирает валидаторы, проектор, планировщик и отчётные настройки.
    """

    def __init__(self, secrets: SecretProviderProtocol | None = None):
        self._report_adapter = employees_report_adapter
        self._apply_adapter = EmployeesApplyAdapter(secrets=secrets)

    def build_planning_deps(self, conn, settings) -> PlanningDependencies:
        resolver_settings = _build_resolver_settings(settings)
        cache_repo = self._build_cache_repo(conn)
        engine = SqliteEngine(conn)
        identity_repo = SqliteIdentityRepository(engine)
        pending_repo = SqlitePendingLinksRepository(engine)
        return PlanningDependencies(
            cache_repo=cache_repo,
            identity_repo=identity_repo,
            pending_repo=pending_repo,
            resolver_settings=resolver_settings,
        )

    def build_enrich_deps(self, conn, settings, secret_store=None) -> EmployeesEnrichDependencies:
        _ = settings
        cache_repo = self._build_cache_repo(conn)
        return EmployeesEnrichDependencies(
            conn=conn,
            cache_repo=cache_repo,
            secret_store=secret_store,
        )

    def build_transform_stages(
        self,
        enrich_deps: EmployeesEnrichDependencies,
        catalog: ErrorCatalog,
    ) -> tuple[MapStage, NormalizeStage, EnrichStage]:
        normalize_spec = load_normalize_spec_for_dataset("employees")
        registry = OperationRegistry()
        register_core_ops(registry)
        normalizer = NormalizerEngine(
            normalize_spec,
            catalog=catalog,
            dsl=NormalizerDsl(registry=registry),
            row_builder=NormalizedEmployeesRow,
        )
        mapper = MapperEngine.from_dataset(catalog=catalog, dataset="employees")
        enrich_registry = OperationRegistry()
        register_core_ops(enrich_registry)
        enricher = EnricherEngine(
            spec=EmployeesEnricherSpec(),
            deps=enrich_deps,
            secret_store=enrich_deps.secret_store,
            dataset="employees",
            catalog=catalog,
            registry=enrich_registry,
            options=EnrichDslBuildOptions(require_match_key=True),
        )
        return (
            MapStage(mapper, catalog),
            NormalizeStage(normalizer, catalog),
            EnrichStage(enricher, catalog),
        )

    def build_cache_specs(self) -> list:
        return [organizations_cache_spec, employees_cache_spec]

    def _build_cache_repo(self, conn) -> SqliteCacheRepository:
        engine = SqliteEngine(conn)
        return SqliteCacheRepository(engine, self.build_cache_specs())

    def build_record_source(
        self,
        csv_has_header: bool,
    ):
        source_spec = load_source_spec_for_dataset("employees")
        if source_spec.source.type != "file" or source_spec.source.format != "csv":
            raise ValueError("employees source spec must be file/csv for current runtime")
        source_path = resolve_source_location(source_spec)
        return CsvRecordSource(source_path, csv_has_header)

    def build_planning_bundle(self) -> PlanningBundle:
        return PlanningBundle(
            matching_rules=build_matching_rules(),
            resolve_rules=build_resolve_rules(),
            link_rules=build_link_rules(),
        )

    def get_report_adapter(self):
        return self._report_adapter

    def get_apply_adapter(self):
        return self._apply_adapter

    def get_diagnostic_catalog(self, strict: bool):
        return build_employees_catalog(strict=strict)

# Фабрика экземпляра спеки
def make_employees_spec(secrets: SecretProviderProtocol | None = None) -> EmployeesSpec:
    return EmployeesSpec(secrets=secrets)


def _build_resolver_settings(settings) -> ResolverSettings:
    if settings is None:
        return ResolverSettings(
            pending_ttl_seconds=120,
            pending_max_attempts=5,
            pending_sweep_interval_seconds=60,
            pending_on_expire="error",
            pending_allow_partial=False,
            pending_retention_days=14,
        )
    return ResolverSettings(
        pending_ttl_seconds=settings.pending_ttl_seconds,
        pending_max_attempts=settings.pending_max_attempts,
        pending_sweep_interval_seconds=settings.pending_sweep_interval_seconds,
        pending_on_expire=settings.pending_on_expire,
        pending_allow_partial=settings.pending_allow_partial,
        pending_retention_days=settings.pending_retention_days,
    )
