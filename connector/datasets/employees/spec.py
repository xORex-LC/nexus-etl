from __future__ import annotations

from connector.datasets.spec import DatasetSpec, TransformBundle, ValidationBundle
from connector.datasets.employees.load.reporting import employees_report_adapter
from connector.datasets.employees.load.apply_adapter import EmployeesApplyAdapter
from connector.domain.planning.deps import PlanningDependencies, ResolverSettings
from connector.datasets.employees.load.matching_rules import build_matching_rules
from connector.datasets.employees.load.link_rules import build_link_rules
from connector.datasets.employees.load.resolve_rules import build_resolve_rules
from connector.domain.validation.deps import ValidationDependencies
from connector.datasets.employees.transform.validation_spec import EmployeesValidationSpec
from connector.domain.ports.secrets import SecretProviderProtocol
from connector.datasets.employees.extract.source_mapper import EmployeesSourceMapper
from connector.datasets.employees.extract.mapping_spec import EmployeesMappingSpec
from connector.datasets.employees.transform.normalizer_spec import EmployeesNormalizerSpec
from connector.datasets.employees.transform.enricher_spec import EmployeesEnricherSpec
from connector.datasets.employees.transform.enrich_deps import EmployeesEnrichDependencies
from connector.domain.transform.enricher import Enricher
from connector.domain.transform.normalizer import Normalizer
from connector.domain.validation.validator import Validator
from connector.infra.sources.csv_reader import CsvRecordSource
from connector.datasets.employees.load.cache_spec import employees_cache_spec
from connector.datasets.organizations.load.cache_spec import organizations_cache_spec
from connector.infra.cache.sqlite_engine import SqliteEngine
from connector.infra.cache.repository import SqliteCacheRepository
from connector.infra.cache.identity_repository import SqliteIdentityRepository
from connector.infra.cache.pending_links_repository import SqlitePendingLinksRepository

class EmployeesSpec(DatasetSpec):
    """
    DatasetSpec для employees: собирает валидаторы, проектор, планировщик и отчётные настройки.
    """

    def __init__(self, secrets: SecretProviderProtocol | None = None):
        self._report_adapter = employees_report_adapter
        self._apply_adapter = EmployeesApplyAdapter(secrets=secrets)

    def build_validation_deps(self, conn, settings) -> ValidationDependencies:
        _ = (conn, settings)
        return ValidationDependencies()

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

    def build_transformers(self, deps: ValidationDependencies, enrich_deps: EmployeesEnrichDependencies) -> TransformBundle:
        _ = deps
        mapping_spec = EmployeesMappingSpec()
        normalizer = Normalizer(EmployeesNormalizerSpec())
        mapper = EmployeesSourceMapper(mapping_spec)
        enricher = Enricher(
            spec=EmployeesEnricherSpec(),
            deps=enrich_deps,
            secret_store=enrich_deps.secret_store,
            dataset="employees",
        )
        return TransformBundle(mapper=mapper, normalizer=normalizer, enricher=enricher)

    def build_validator(self, deps: ValidationDependencies) -> ValidationBundle:
        validator = Validator(EmployeesValidationSpec(), deps)
        return ValidationBundle(validator=validator)

    def build_cache_specs(self) -> list:
        return [organizations_cache_spec, employees_cache_spec]

    def _build_cache_repo(self, conn) -> SqliteCacheRepository:
        engine = SqliteEngine(conn)
        return SqliteCacheRepository(engine, self.build_cache_specs())

    def build_record_source(
        self,
        csv_path: str,
        csv_has_header: bool,
    ):
        return CsvRecordSource(csv_path, csv_has_header)

    def build_matching_rules(self):
        return build_matching_rules()

    def build_resolve_rules(self):
        return build_resolve_rules()

    def build_link_rules(self):
        return build_link_rules()

    def get_report_adapter(self):
        return self._report_adapter

    def get_apply_adapter(self):
        return self._apply_adapter

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
