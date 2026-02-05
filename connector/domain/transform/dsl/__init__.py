"""
Назначение:
    DSL ядро трансформаций (правила, операции, движок).
"""

from connector.domain.transform.dsl.engine import EngineResult, TransformationEngine
from connector.domain.transform.dsl.issues import DslIssue, DslSeverity
from connector.domain.transform.dsl.loader import (
    load_mapping_spec,
    load_mapping_spec_for_dataset,
    load_normalize_spec_for_dataset,
    load_enrich_spec_for_dataset,
    load_validate_spec_for_dataset,
    load_match_spec_for_dataset,
    load_resolve_spec_for_dataset,
)
from connector.domain.transform.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.transform.dsl.specs import (
    MappingSpec,
    MappingRule,
    OperationCall,
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
    "load_normalize_spec_for_dataset",
    "load_enrich_spec_for_dataset",
    "load_validate_spec_for_dataset",
    "load_match_spec_for_dataset",
    "load_resolve_spec_for_dataset",
    "OperationRegistry",
    "register_core_ops",
    "MappingSpec",
    "MappingRule",
    "OperationCall",
    "NormalizeSpec",
    "EnrichSpec",
    "ValidationSpec",
    "MatchSpec",
    "ResolveSpec",
]
