"""
Назначение:
    EnricherEngine: DSL-обвязка enrich-стадии (StageEngine).

Граница ответственности:
    - Owns: компиляция EnrichSpec → EnricherCore.
    - Does NOT: бизнес-логика обогащения (делегирует EnricherCore).

    Поддерживает два пути инициализации (DEC-004 transition):
    - ctx: StageExecutionContext — новый путь (capabilities из context).
    - scattered params (deps, secret_store, dataset, catalog) — legacy путь.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Generic, TypeVar

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.cache.roles import EnrichLookupPort
from connector.domain.ports.secrets.provider import SecretStoreProtocol
from connector.domain.ports.transform.dictionaries import DictionaryProviderPort
from connector.domain.transform.core.result import TransformResult
from connector.domain.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.transform_dsl.build_options import EnrichDslBuildOptions
from connector.domain.transform_dsl.specs import EnrichSpec, SinkSpec
from connector.domain.transform.enrich.enricher_core import EnricherCore
from connector.domain.transform_dsl.compilers.enrich import EnricherDsl
from connector.domain.transform.providers import ProviderGateway

if TYPE_CHECKING:
    from connector.domain.transform.context import StageExecutionContext

T = TypeVar("T")
D = TypeVar("D")


class EnricherEngine(Generic[T, D]):
    """
    Назначение/ответственность:
        DSL-движок стадии enrich: компилирует EnrichSpec и запускает EnricherCore.

    Поддерживает два пути инициализации (DEC-004 transition):
        - ctx: StageExecutionContext — scoped capabilities (новый путь).
        - deps/secret_store/dataset/catalog — scattered params (legacy путь).
    """

    def __init__(
        self,
        *,
        spec: EnrichSpec,
        ctx: StageExecutionContext | None = None,
        deps: D | None = None,
        secret_store: SecretStoreProtocol | None = None,
        dataset: str | None = None,
        catalog: ErrorCatalog | None = None,
        registry: OperationRegistry | None = None,
        providers: ProviderGateway | None = None,
        options: EnrichDslBuildOptions | None = None,
        sink_spec: SinkSpec | None = None,
        run_id: str | None = None,
    ) -> None:
        if ctx is not None:
            resolved_deps = ctx.get(EnrichLookupPort)
            resolved_secret_store = ctx.get(SecretStoreProtocol)
            resolved_dictionaries = ctx.get(DictionaryProviderPort)
            resolved_dataset = ctx.metadata.dataset_name
            resolved_catalog = ctx.metadata.catalog
            resolved_sink_spec = sink_spec or ctx.metadata.sink_spec
            resolved_run_id = run_id or ctx.metadata.run_id

            # Build a lightweight deps-like namespace for EnricherCore
            from types import SimpleNamespace
            effective_deps = SimpleNamespace(
                cache_gateway=resolved_deps,
                secret_store=resolved_secret_store,
                dictionaries=resolved_dictionaries,
            )
        else:
            effective_deps = deps
            resolved_secret_store = secret_store
            resolved_dataset = dataset or ""
            resolved_catalog = catalog or ErrorCatalog(dataset=resolved_dataset, items={})
            resolved_sink_spec = sink_spec
            resolved_run_id = run_id

        # NOTE: registry/providers are test and migration hooks.
        # DatasetSpec production path should rely on defaults and build options.
        if registry is None:
            registry = OperationRegistry()
            register_core_ops(registry)
        if providers is None:
            providers = ProviderGateway.with_defaults()
        core_spec = EnricherDsl(registry=registry, providers=providers, options=options).compile(spec)
        self.core = EnricherCore(
            spec=core_spec,
            deps=effective_deps,
            secret_store=resolved_secret_store,
            dataset=resolved_dataset,
            catalog=resolved_catalog,
            sink_spec=resolved_sink_spec,
            run_id=resolved_run_id,
        )

    def enrich(self, result: TransformResult[T]) -> TransformResult[T]:
        return self.core.enrich(result)
