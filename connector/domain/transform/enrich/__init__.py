"""
Enrich package: core enrich logic and DSL wiring.

DSL compiler (EnricherDsl, EnricherSpec, EnrichmentOperation, KeyRegistry, build_enricher_spec_from_dsl)
живёт в connector.domain.transform_dsl.compilers.enrich.
"""

from __future__ import annotations

from importlib import import_module

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

_EXPORTS: dict[str, tuple[str, str]] = {
    "CandidateDecision": (".models", "CandidateDecision"),
    "CandidateProvider": (".providers", "CandidateProvider"),
    "CandidateValue": (".models", "CandidateValue"),
    "ConflictResolver": (".resolver", "ConflictResolver"),
    "EnrichContext": (".models", "EnrichContext"),
    "EnrichEvent": (".models", "EnrichEvent"),
    "EnrichOperationType": (".models", "EnrichOperationType"),
    "EnrichOutcome": (".models", "EnrichOutcome"),
    "EnricherCore": (".enricher_core", "EnricherCore"),
    "EnricherEngine": (".enricher_engine", "EnricherEngine"),
    "EnricherReport": (".report", "EnricherReport"),
    "MergeEngine": (".resolver", "MergeEngine"),
    "MergeMode": (".models", "MergeMode"),
    "MergePolicy": (".models", "MergePolicy"),
    "OperationReport": (".models", "OperationReport"),
    "ResolveHint": (".models", "ResolveHint"),
    "RunWhenErrors": (".models", "RunWhenErrors"),
    "StrictnessPolicy": (".models", "StrictnessPolicy"),
}


def __getattr__(name: str):
    export = _EXPORTS.get(name)
    if export is None:
        raise AttributeError(name)
    module_name, attr_name = export
    module = import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value
