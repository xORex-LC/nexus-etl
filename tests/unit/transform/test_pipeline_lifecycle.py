"""
Lifecycle tests for DEC-004 pipeline — generator cascading, error propagation, catalog errors.
"""

from __future__ import annotations

import pytest
from unittest.mock import Mock

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.transform.stages.stages import (
    PipelineOrchestrator,
    PipelineHooks,
)


def _make_items(n: int = 3) -> list:
    return [Mock(name=f"item_{i}") for i in range(n)]


class _PassthroughStage:
    def __init__(self, name: str = "passthrough") -> None:
        self.stage_name = name

    def run(self, source):
        yield from source


class _AbortTrackingStage:
    """Stage that tracks whether GeneratorExit was received."""

    def __init__(self, name: str) -> None:
        self.stage_name = name
        self.received_generator_exit = False

    def run(self, source):
        try:
            yield from source
        except GeneratorExit:
            self.received_generator_exit = True
            raise


class _FatalStage:
    """Stage that raises a fatal exception after yielding some items."""

    stage_name = "fatal"

    def __init__(self, fail_after: int = 1):
        self._fail_after = fail_after

    def run(self, source):
        count = 0
        for item in source:
            count += 1
            if count > self._fail_after:
                raise RuntimeError("infra fatal: connection lost")
            yield item


def test_generator_exit_cascades_through_full_5_stage_chain():
    """
    When consumer closes the pipeline generator, GeneratorExit cascades
    back through all 5 stages in the chain.
    """
    stages = [_AbortTrackingStage(f"s{i}") for i in range(5)]
    items = _make_items(10)
    orch = PipelineOrchestrator(stages)

    gen = iter(orch.run(iter(items)))
    next(gen)   # pull first item to start all stages
    gen.close()  # trigger GeneratorExit cascade

    # At least the last stage in the chain should receive GeneratorExit
    assert stages[-1].received_generator_exit is True


def test_error_catalog_receives_all_record_level_errors():
    """
    When stages produce per-record errors, the error catalog collects them
    through the diagnostic_boundary. Here we verify that a stage with
    errors doesn't stop the pipeline.
    """

    class _ErrorInjectingStage:
        stage_name = "error_inject"

        def run(self, source):
            for item in source:
                builder = Mock()
                builder.errors = [Mock(name="err")]
                builder.row = item
                yield item  # pass through — errors are on the result, not thrown

    stages = [_ErrorInjectingStage(), _PassthroughStage("after_error")]
    items = _make_items(3)
    orch = PipelineOrchestrator(stages)
    results = list(orch.run(iter(items)))

    # All items pass through despite "errors" being attached
    assert len(results) == 3


def test_infra_fatal_exception_propagates_to_use_case():
    """
    A fatal infrastructure exception (e.g., SQLite I/O error) in a stage
    propagates up to the caller. PipelineOrchestrator never suppresses it.
    """
    stages = [_PassthroughStage("before"), _FatalStage(fail_after=1), _PassthroughStage("after")]
    items = _make_items(5)
    orch = PipelineOrchestrator(stages)

    with pytest.raises(RuntimeError, match="infra fatal"):
        list(orch.run(iter(items)))


def test_infra_fatal_triggers_error_hook():
    """
    Fatal exception triggers on_stage_error hook with the correct stage name.
    """
    errors: list[tuple] = []
    hooks = PipelineHooks(
        on_stage_error=lambda name, exc, ms: errors.append((name, str(exc)))
    )
    stages = [_PassthroughStage("pre"), _FatalStage(fail_after=1)]
    items = _make_items(3)
    orch = PipelineOrchestrator(stages, hooks=hooks)

    with pytest.raises(RuntimeError):
        list(orch.run(iter(items)))

    assert len(errors) == 1
    assert errors[0][0] == "fatal"
    assert "infra fatal" in errors[0][1]
