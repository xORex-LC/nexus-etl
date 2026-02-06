"""
Назначение:
    EnricherEngine: DSL-обвязка enrich-стадии (StageEngine).
"""

from __future__ import annotations

from typing import Generic, TypeVar

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.ports.secrets.provider import SecretStoreProtocol
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.transform.dsl.specs import EnrichSpec
from connector.domain.transform.enrich.enricher_core import EnricherCore
from connector.domain.transform.enrich.enricher_dsl import EnrichDslBuildOptions, EnricherDsl
from connector.domain.transform.providers import ProviderRegistry, register_builtin_providers

T = TypeVar("T")
D = TypeVar("D")


class EnricherEngine(Generic[T, D]):
    """
    Назначение/ответственность:
        DSL-движок стадии enrich: компилирует EnrichSpec и запускает EnricherCore.
    """

    def __init__(
        self,
        *,
        spec: EnrichSpec,
        deps: D,
        secret_store: SecretStoreProtocol | None,
        dataset: str,
        catalog: ErrorCatalog,
        registry: OperationRegistry | None = None,
        providers: ProviderRegistry | None = None,
        options: EnrichDslBuildOptions | None = None,
        run_id: str | None = None,
    ) -> None:
        if registry is None:
            registry = OperationRegistry()
            register_core_ops(registry)
        if providers is None:
            providers = ProviderRegistry()
            register_builtin_providers(providers)
        core_spec = EnricherDsl(registry=registry, providers=providers, options=options).compile(spec)
        self.core = EnricherCore(
            spec=core_spec,
            deps=deps,
            secret_store=secret_store,
            dataset=dataset,
            catalog=catalog,
            run_id=run_id,
        )

    def enrich(self, result: TransformResult[T]) -> TransformResult[T]:
        return self.core.enrich(result)
