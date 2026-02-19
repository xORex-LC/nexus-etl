from __future__ import annotations

from typing import Any

from connector.datasets.apply_adapter import OperationApplyAdapter
from connector.datasets.spec import (
    DatasetSpec,
    ReportAdapter,
)
from connector.domain.ports.cache.roles import EnrichLookupPort, PlanningRuntimePort
from connector.domain.transform.resolver.resolve_deps import PlanningDependencies, ResolverSettings
from connector.domain.ports.secrets.provider import SecretProviderProtocol
from connector.domain.planning.plan_models import PlanItem
from connector.domain.transform.mapping import MapperEngine
from connector.domain.transform.matcher.match_engine import MatchEngine
from connector.domain.transform_dsl import (
    load_enrich_build_options_for_dataset,
    load_enrich_spec_for_dataset,
    load_map_build_options_for_dataset,
    load_mapping_spec_for_dataset,
    load_match_build_options_for_dataset,
    load_match_spec_for_dataset,
    load_normalize_build_options_for_dataset,
    load_normalize_spec_for_dataset,
    load_resolve_build_options_for_dataset,
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
from connector.domain.transform.enrich import EnricherEngine
from connector.domain.transform_dsl.compilers.resolve import ResolveDsl
from connector.domain.transform.resolver.resolve_engine import ResolveEngine
from connector.domain.transform.normalize import NormalizerEngine
from connector.domain.transform.stages.stages import (
    EnrichStage,
    MapStage,
    MatchStage,
    NormalizeStage,
    ResolveStage,
)
from connector.domain.transform.providers import TransformProviderDeps
from connector.infra.sources.csv_reader import CsvRecordSource
from connector.infra.target.providers.ankey_rest.payloads import (
    build_user_upsert_payload,
)
from connector.datasets.employees.diagnostic_catalog import build_employees_catalog
from connector.domain.diagnostics.catalog import ErrorCatalog

class EmployeesSpec(DatasetSpec):
    """
    DatasetSpec для employees: собирает валидаторы, проектор, планировщик и отчётные настройки.
    """

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

    def build_planning_deps(
        self,
        settings,
        *,
        planning_runtime: PlanningRuntimePort,
    ) -> PlanningDependencies:
        resolver_settings = _build_resolver_settings(settings)
        return PlanningDependencies(
            cache_gateway=planning_runtime,
            resolver_settings=resolver_settings,
        )

    def build_enrich_deps(
        self,
        settings,
        *,
        enrich_lookup: EnrichLookupPort,
        secret_store=None,
    ) -> TransformProviderDeps:
        _ = settings
        return TransformProviderDeps(
            cache_gateway=enrich_lookup,
            secret_store=secret_store,
        )

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

    def build_map_stage(self, *, catalog: ErrorCatalog) -> MapStage:
        options = load_map_build_options_for_dataset(self.dataset_name)
        mapper = MapperEngine(
            self.build_map_spec(),
            catalog=catalog,
            sink_spec=self.build_sink_spec(),
            options=options,
        )
        return MapStage(mapper, catalog)

    def build_normalize_stage(self, *, catalog: ErrorCatalog) -> NormalizeStage:
        options = load_normalize_build_options_for_dataset(self.dataset_name)
        normalizer = NormalizerEngine(
            self.build_normalize_spec(),
            catalog=catalog,
            sink_spec=self.build_sink_spec(),
            row_builder=NormalizedEmployeesRow,
            options=options,
        )
        return NormalizeStage(normalizer, catalog)

    def build_enrich_stage(
        self,
        *,
        catalog: ErrorCatalog,
        enrich_deps: TransformProviderDeps,
    ) -> EnrichStage:
        options = load_enrich_build_options_for_dataset(self.dataset_name)
        enricher = EnricherEngine(
            spec=self.build_enrich_spec(),
            deps=enrich_deps,
            secret_store=enrich_deps.secret_store,
            dataset=self.dataset_name,
            catalog=catalog,
            options=options,
            sink_spec=self.build_sink_spec(),
        )
        return EnrichStage(enricher, catalog)

    def build_match_stage(
        self,
        *,
        planning_deps: PlanningDependencies,
        catalog: ErrorCatalog,
        include_deleted: bool,
        settings=None,
    ) -> MatchStage:
        planning_runtime = planning_deps.cache_gateway
        if planning_runtime is None:
            raise ValueError("planning runtime is not configured")
        compiled_resolve = self._compile_resolve(settings=settings)
        options = load_match_build_options_for_dataset(self.dataset_name)
        matcher = MatchEngine(
            spec=self.build_match_spec(settings=settings),
            dataset=self.dataset_name,
            cache_gateway=planning_runtime,
            resolve_rules=compiled_resolve.resolve_rules,
            include_deleted=include_deleted,
            catalog=catalog,
            options=options,
        )
        return MatchStage(matcher, catalog)

    def build_resolve_stage(
        self,
        *,
        planning_deps: PlanningDependencies,
        catalog: ErrorCatalog,
        settings=None,
    ) -> ResolveStage:
        options = load_resolve_build_options_for_dataset(self.dataset_name)
        planning_runtime = planning_deps.cache_gateway
        if planning_runtime is None:
            raise ValueError("planning runtime is not configured")
        resolver = ResolveEngine(
            spec=self.build_resolve_spec(settings=settings),
            cache_gateway=planning_runtime,
            settings=planning_deps.resolver_settings,
            catalog=catalog,
            sink_spec=self.build_sink_spec(settings=settings),
            options=options,
        )
        return ResolveStage(resolver, catalog)

    def build_transform_stages(
        self,
        *,
        enrich_deps: TransformProviderDeps,
        catalog: ErrorCatalog,
    ) -> tuple[MapStage, NormalizeStage, EnrichStage]:
        return (
            self.build_map_stage(catalog=catalog),
            self.build_normalize_stage(catalog=catalog),
            self.build_enrich_stage(catalog=catalog, enrich_deps=enrich_deps),
        )

    def build_planning_stages(
        self,
        *,
        planning_deps: PlanningDependencies,
        catalog: ErrorCatalog,
        include_deleted: bool,
        settings=None,
    ) -> tuple[MatchStage, ResolveStage]:
        return (
            self.build_match_stage(
                planning_deps=planning_deps,
                catalog=catalog,
                include_deleted=include_deleted,
                settings=settings,
            ),
            self.build_resolve_stage(
                planning_deps=planning_deps,
                catalog=catalog,
                settings=settings,
            ),
        )

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

    def _compile_resolve(self, settings=None):
        resolve_spec = self.build_resolve_spec(settings=settings)
        return ResolveDsl().compile(resolve_spec, sink_spec=self.build_sink_spec(settings=settings))

# Фабрика экземпляра спеки
def make_employees_spec(secrets: SecretProviderProtocol | None = None) -> EmployeesSpec:
    return EmployeesSpec(secrets=secrets, dataset_name="employees")


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


def _build_employees_operation_params(item: PlanItem) -> dict[str, Any]:
    target_id = item.target_id
    if target_id is None:
        raise ValueError("target_id is required for operation users.upsert")
    normalized = str(target_id).strip()
    if normalized == "":
        raise ValueError("target_id is required for operation users.upsert")
    return {"target_id": normalized}
