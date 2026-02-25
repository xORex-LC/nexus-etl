"""
Architecture tests for DEC-004 pipeline — statelessness and resource invariants.
"""

from __future__ import annotations

from unittest.mock import Mock

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.transform.stages.stages import (
    MapStage,
    NormalizeStage,
    EnrichStage,
    MatchStage,
    ResolveContextStage,
    ResolveStage,
    MatchProcessor,
    ResolveProcessor,
    StageContract,
)


def _make_catalog() -> ErrorCatalog:
    return Mock(spec=ErrorCatalog)


def test_invariant_stages_are_stateless():
    """
    All 6 concrete stages have no mutable per-run state.
    They delegate to injected engines and carry only immutable references.
    Re-running the same stage with fresh source yields independent results.
    Private attributes (_batch_index etc.) are excluded from the check (they're DI-injected).
    """
    catalog = _make_catalog()

    map_stage = MapStage(mapper=Mock(), catalog=catalog)
    norm_stage = NormalizeStage(normalizer=Mock(), catalog=catalog)
    enrich_stage = EnrichStage(enricher=Mock(), catalog=catalog)
    match_stage = MatchStage(matcher=Mock(spec=MatchProcessor), catalog=catalog)
    resolve_context_stage = ResolveContextStage(batch_index=Mock(), resolver=Mock(spec=ResolveProcessor))
    resolve_stage = ResolveStage(
        resolver=Mock(spec=ResolveProcessor), catalog=catalog, batch_index=Mock()
    )

    stages = [map_stage, norm_stage, enrich_stage, match_stage, resolve_context_stage, resolve_stage]
    for stage in stages:
        assert isinstance(stage, StageContract)
        # No __dict__ keys beyond constructor-injected attributes
        mutable_keys = {
            k for k, v in vars(stage).items()
            if not k.startswith("_") and not callable(v)
        }
        # Only engine + catalog references, no per-run buffers
        assert mutable_keys <= {"mapper", "normalizer", "enricher", "matcher", "resolver", "catalog"}, (
            f"{type(stage).__name__} has unexpected mutable state: {mutable_keys}"
        )


def test_long_lived_resource_not_closed_by_stage_on_generator_exit():
    """
    When a pipeline generator is closed (GeneratorExit), stages must NOT
    close injected long-lived resources (engines, caches). Only the DI
    container owns their lifecycle.

    Uses stub stages with mock engine references to verify no .close() is called.
    """
    from connector.domain.transform.stages.stages import PipelineOrchestrator

    engine_mocks = []

    class _StageWithEngine:
        def __init__(self, name: str):
            self.stage_name = name
            self.engine = Mock()
            engine_mocks.append(self.engine)

        def run(self, source):
            yield from source

    stages = [_StageWithEngine(f"s{i}") for i in range(3)]
    items = [Mock() for _ in range(5)]

    orch = PipelineOrchestrator(stages)
    gen = iter(orch.run(iter(items)))
    next(gen)  # pull one item to start pipeline
    gen.close()  # trigger GeneratorExit cascade

    # Engines must NOT have close() called by stages
    for engine_mock in engine_mocks:
        assert not engine_mock.close.called, "Stage must not close injected engine on GeneratorExit"
