"""
Назначение:
    DSL ядро трансформаций (правила, операции, движок).
"""

from connector.domain.dsl.engine import EngineResult, TransformationEngine
from connector.domain.dsl.issues import DslIssue, DslSeverity
from connector.domain.dsl.loader import (
    load_source_spec_for_dataset,
    load_mapping_spec,
    load_mapping_spec_for_dataset,
    load_normalize_spec_for_dataset,
    load_enrich_spec_for_dataset,
    load_validate_spec_for_dataset,
    load_match_spec_for_dataset,
    load_resolve_spec_for_dataset,
    load_sink_spec_for_dataset,
    load_map_build_options_for_dataset,
    load_normalize_build_options_for_dataset,
    load_enrich_build_options_for_dataset,
    load_match_build_options_for_dataset,
    load_resolve_build_options_for_dataset,
)
from connector.domain.dsl.build_options import (
    BaseDslBuildOptions,
    MapDslBuildOptions,
    NormalizeDslBuildOptions,
    EnrichDslBuildOptions,
    MatchDslBuildOptions,
    ResolveDslBuildOptions,
)
from connector.domain.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.dsl.specs import (
    MappingSpec,
    MappingRule,
    OperationCall,
    ProviderRef,
    ExistsRef,
    NormalizeSpec,
    EnrichSpec,
    ValidationSpec,
    MatchSpec,
    ResolveSpec,
)

__all__ = [
    "EngineResult",
    "TransformationEngine",
    "DslIssue",
    "DslSeverity",
    "load_mapping_spec",
    "load_mapping_spec_for_dataset",
    "load_source_spec_for_dataset",
    "load_normalize_spec_for_dataset",
    "load_enrich_spec_for_dataset",
    "load_validate_spec_for_dataset",
    "load_match_spec_for_dataset",
    "load_resolve_spec_for_dataset",
    "load_sink_spec_for_dataset",
    "load_map_build_options_for_dataset",
    "load_normalize_build_options_for_dataset",
    "load_enrich_build_options_for_dataset",
    "load_match_build_options_for_dataset",
    "load_resolve_build_options_for_dataset",
    "BaseDslBuildOptions",
    "MapDslBuildOptions",
    "NormalizeDslBuildOptions",
    "EnrichDslBuildOptions",
    "MatchDslBuildOptions",
    "ResolveDslBuildOptions",
    "OperationRegistry",
    "register_core_ops",
    "MappingSpec",
    "MappingRule",
    "OperationCall",
    "ProviderRef",
    "ExistsRef",
    "NormalizeSpec",
    "EnrichSpec",
    "ValidationSpec",
    "MatchSpec",
    "ResolveSpec",
]
