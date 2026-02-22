"""Stage orchestration for data transform pipeline."""

from connector.domain.transform.stages.stages import (
    # ── Canonical (DEC-004) ───────────────────────────────────────────────
    StageContract,
    AnyStageContract,
    BatchConfig,
    BatchableStage,
    PipelineHooks,
    PipelineOrchestrator,
    # ── Engine protocols ─────────────────────────────────────────────────
    MatchProcessor,
    ResolveProcessor,
    # ── Stage implementations ────────────────────────────────────────────
    MapStage,
    NormalizeStage,
    EnrichStage,
    MatchStage,
    ResolveStage,
    # ── Legacy (backward-compat; removed in DEC-004 Stage 5) ────────────
    TransformStageProcessor,
    StagePipeline,
    batched,
)

__all__ = [
    # Canonical
    "StageContract",
    "AnyStageContract",
    "BatchConfig",
    "BatchableStage",
    "PipelineHooks",
    "PipelineOrchestrator",
    # Engine protocols
    "MatchProcessor",
    "ResolveProcessor",
    # Stage implementations
    "MapStage",
    "NormalizeStage",
    "EnrichStage",
    "MatchStage",
    "ResolveStage",
    # Legacy
    "TransformStageProcessor",
    "StagePipeline",
    "batched",
]
