from __future__ import annotations

from dataclasses import dataclass

from connector.domain.dsl import (
    CacheDatasetSpec,
    CacheRegistrySpec,
    compile_cache_runtime,
    load_cache_dataset_spec_for_dataset,
    load_cache_registry_spec_for_runtime,
)
from connector.domain.dsl.cache_compiler import CacheDslRuntime
from connector.infra.cache.sync import build_dsl_cache_sync_adapter


@dataclass(frozen=True)
class CacheDslRuntimeBundle:
    """
    Полный runtime bundle cache DSL: registry + dataset specs + compiled runtime.
    """

    registry_spec: CacheRegistrySpec
    dataset_specs: dict[str, CacheDatasetSpec]
    runtime: CacheDslRuntime

    @property
    def cache_specs(self):
        return self.runtime.cache_specs


def load_cache_dsl_runtime() -> CacheDslRuntimeBundle:
    """
    Назначение:
        Загрузить cache DSL (registry + dataset specs) и скомпилировать runtime.
    """
    registry_spec = load_cache_registry_spec_for_runtime()
    dataset_specs: dict[str, CacheDatasetSpec] = {}
    for dataset, entry in registry_spec.datasets.items():
        if not entry.enabled:
            continue
        dataset_specs[dataset] = load_cache_dataset_spec_for_dataset(dataset)

    runtime = compile_cache_runtime(
        registry_spec=registry_spec,
        dataset_specs=dataset_specs,
    )
    return CacheDslRuntimeBundle(
        registry_spec=registry_spec,
        dataset_specs=dataset_specs,
        runtime=runtime,
    )


def build_sync_adapters(bundle: CacheDslRuntimeBundle):
    """
    Назначение:
        Построить runtime sync adapters в dependency-safe порядке.
    """
    adapters = []
    for dataset in bundle.runtime.dependency_graph.refresh_order():
        sync_spec = bundle.runtime.sync_specs.get(dataset)
        if sync_spec is None:
            continue
        dataset_spec = bundle.dataset_specs[dataset]
        adapters.append(
            build_dsl_cache_sync_adapter(
                dataset_spec=dataset_spec,
                sync_spec=sync_spec,
            )
        )
    return adapters
