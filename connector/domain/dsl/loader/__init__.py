"""
Назначение:
    DSL loader public API.
"""

from connector.domain.dsl.loader.cache import (
    load_cache_build_options_for_runtime,
    load_cache_dataset_spec,
    load_cache_dataset_spec_for_dataset,
    load_cache_registry_spec,
    load_cache_registry_spec_for_runtime,
)
from connector.domain.dsl.loader.transform import (
    load_enrich_build_options_for_dataset,
    load_enrich_spec_for_dataset,
    load_map_build_options_for_dataset,
    load_mapping_spec,
    load_mapping_spec_for_dataset,
    load_match_build_options_for_dataset,
    load_match_spec_for_dataset,
    load_normalize_build_options_for_dataset,
    load_normalize_spec_for_dataset,
    load_resolve_build_options_for_dataset,
    load_resolve_spec_for_dataset,
    load_sink_spec_for_dataset,
    load_source_spec_for_dataset,
    load_validate_spec_for_dataset,
    resolve_source_location,
)

__all__ = [
    # Transform loaders
    "load_mapping_spec",
    "load_mapping_spec_for_dataset",
    "load_source_spec_for_dataset",
    "resolve_source_location",
    "load_normalize_spec_for_dataset",
    "load_enrich_spec_for_dataset",
    "load_validate_spec_for_dataset",
    "load_match_spec_for_dataset",
    "load_resolve_spec_for_dataset",
    "load_sink_spec_for_dataset",
    # Transform build options
    "load_map_build_options_for_dataset",
    "load_normalize_build_options_for_dataset",
    "load_enrich_build_options_for_dataset",
    "load_match_build_options_for_dataset",
    "load_resolve_build_options_for_dataset",
    # Cache loaders
    "load_cache_registry_spec",
    "load_cache_registry_spec_for_runtime",
    "load_cache_dataset_spec",
    "load_cache_dataset_spec_for_dataset",
    # Cache build options
    "load_cache_build_options_for_runtime",
]
