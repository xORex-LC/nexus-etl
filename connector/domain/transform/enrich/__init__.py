"""
Enrich package: core enrich logic and DSL wiring.
"""

from .enricher_dsl import EnrichDslBuildOptions, EnricherDsl, build_enricher_spec_from_dsl
from .enricher_engine import EnricherEngine
from .enricher_core import EnricherCore
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
    "EnricherCore",
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
    "EnricherDsl",
]
