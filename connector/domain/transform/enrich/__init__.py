"""
Enrich package: core enrich logic and DSL wiring.

DSL compiler (EnricherDsl, EnricherSpec, EnrichmentOperation, KeyRegistry, build_enricher_spec_from_dsl)
живёт в connector.domain.transform_dsl.compilers.enrich.
"""

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
    "MergeEngine",
    "MergeMode",
    "MergePolicy",
    "OperationReport",
    "ResolveHint",
    "RunWhenErrors",
    "StrictnessPolicy",
    "EnricherReport",
]
