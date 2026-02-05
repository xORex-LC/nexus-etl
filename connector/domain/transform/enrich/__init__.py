"""
Enrich package: core enrich logic and DSL wiring.
"""

from .dsl import EnrichDslBuildOptions, build_enricher_spec_from_dsl
from .engine import EnricherEngine
from .models import (
    CandidateDecision,
    CandidateValue,
    EnrichContext,
    EnrichEvent,
    EnrichOperationType,
    EnrichOutcome,
    MergeMode,
    MergePolicy,
    OperationReport,
    ResolveHint,
    RunWhenErrors,
    StrictnessPolicy,
)
from .providers import CandidateProvider
from .report import EnricherReport
from .resolver import ConflictResolver, MergeEngine
from .spec import EnricherSpec, EnrichmentOperation, KeyRegistry

__all__ = [
    "CandidateDecision",
    "CandidateProvider",
    "CandidateValue",
    "ConflictResolver",
    "EnrichContext",
    "EnrichEvent",
    "EnrichOperationType",
    "EnrichOutcome",
    "EnricherEngine",
    "EnricherSpec",
    "EnrichmentOperation",
    "KeyRegistry",
    "MergeEngine",
    "MergeMode",
    "MergePolicy",
    "OperationReport",
    "ResolveHint",
    "RunWhenErrors",
    "StrictnessPolicy",
    "EnricherReport",
    "build_enricher_spec_from_dsl",
    "EnrichDslBuildOptions",
]
