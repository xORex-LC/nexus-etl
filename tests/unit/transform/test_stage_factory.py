"""
Tests for StageFactory and StageDescriptor (DEC-004 Stage 3 / Stage 4).

Architecture:
    - StageDescriptor is a frozen dataclass.
    - StageFactory.create() does no I/O.
    - Fail-fast: required_capabilities checked BEFORE engine_factory.

Unit:
    - Unknown stage_type → ValueError.
    - Duplicate registration → ValueError.
    - Missing capability → MissingCapabilityError.
    - create() calls engine_factory then stage_wrapper.
    - Introspection via registered_types.

Integration:
    - build_stage_factory() registers all 6 stage types (incl. resolve_context).
    - resolve_context и resolve зарегистрированы для introspection;
      create() для них бросает NotImplementedError (создаются напрямую в PipelineContainer).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from unittest.mock import Mock, call

import pytest

from connector.domain.transform.context import (
    MissingCapabilityError,
    PipelineMetadata,
    StageExecutionContext,
)
from connector.domain.transform.factory import StageDescriptor, StageFactory
from connector.domain.diagnostics.catalog import ErrorCatalog


# ════════════════════════════════════════════════════════════════════════════════
# Test helpers
# ════════════════════════════════════════════════════════════════════════════════

@runtime_checkable
class _StubPort(Protocol):
    def do_stuff(self) -> None: ...


@runtime_checkable
class _AnotherPort(Protocol):
    def do_other(self) -> None: ...


def _make_metadata(**overrides) -> PipelineMetadata:
    defaults = dict(
        run_id="run-001",
        dataset_name="test_ds",
        catalog=Mock(spec=ErrorCatalog),
        sink_spec=None,
    )
    defaults.update(overrides)
    return PipelineMetadata(**defaults)


def _make_context(
    capabilities: dict[type, object] | None = None,
    **meta_overrides,
) -> StageExecutionContext:
    return StageExecutionContext(
        metadata=_make_metadata(**meta_overrides),
        capabilities=capabilities or {},
    )


def _make_descriptor(
    stage_type: str = "test_stage",
    *,
    engine_factory=None,
    stage_wrapper=None,
    required_capabilities: frozenset[type] | None = None,
) -> StageDescriptor:
    if engine_factory is None:
        engine_factory = Mock(return_value=Mock())
    if stage_wrapper is None:
        stage_wrapper = Mock(return_value=Mock())
    return StageDescriptor(
        stage_type=stage_type,
        engine_factory=engine_factory,
        stage_wrapper=stage_wrapper,
        required_capabilities=required_capabilities or frozenset(),
    )


# ════════════════════════════════════════════════════════════════════════════════
# Architecture tests
# ════════════════════════════════════════════════════════════════════════════════

class TestArchitecture:

    def test_stage_descriptor_is_frozen_dataclass(self):
        desc = _make_descriptor()
        with pytest.raises(AttributeError):
            desc.stage_type = "changed"  # type: ignore[misc]


# ════════════════════════════════════════════════════════════════════════════════
# Unit tests: StageFactory
# ════════════════════════════════════════════════════════════════════════════════

class TestStageFactoryRegistration:

    def test_unknown_type_raises_value_error(self):
        factory = StageFactory()
        ctx = _make_context()

        with pytest.raises(ValueError, match="Unknown stage type: missing"):
            factory.create("missing", Mock(), ctx)

    def test_duplicate_registration_raises_value_error(self):
        factory = StageFactory()
        desc = _make_descriptor(stage_type="map")
        factory.register(desc)

        with pytest.raises(ValueError, match="already registered: map"):
            factory.register(_make_descriptor(stage_type="map"))

    def test_introspection_returns_registered_types(self):
        factory = StageFactory()
        factory.register(_make_descriptor(stage_type="map"))
        factory.register(_make_descriptor(stage_type="enrich"))
        factory.register(_make_descriptor(stage_type="resolve"))

        assert factory.registered_types == ["map", "enrich", "resolve"]


class TestStageFactoryCreate:

    def test_create_calls_engine_factory_with_kwargs(self):
        engine = Mock()
        engine_factory = Mock(return_value=engine)
        stage_wrapper = Mock(return_value=Mock())
        desc = _make_descriptor(
            engine_factory=engine_factory,
            stage_wrapper=stage_wrapper,
        )
        factory = StageFactory()
        factory.register(desc)

        spec = Mock()
        ctx = _make_context()
        factory.create("test_stage", spec, ctx, option_a="value_a")

        engine_factory.assert_called_once_with(spec, ctx, option_a="value_a")

    def test_create_calls_stage_wrapper(self):
        engine = Mock()
        engine_factory = Mock(return_value=engine)
        stage = Mock()
        stage_wrapper = Mock(return_value=stage)
        desc = _make_descriptor(
            engine_factory=engine_factory,
            stage_wrapper=stage_wrapper,
        )
        factory = StageFactory()
        factory.register(desc)

        ctx = _make_context()
        result = factory.create("test_stage", Mock(), ctx)

        stage_wrapper.assert_called_once_with(engine, ctx)
        assert result is stage

    def test_no_io_in_create(self):
        """create() delegates to engine_factory and stage_wrapper — no I/O itself."""
        call_log = []
        engine = Mock()

        def mock_engine_factory(spec, ctx, **kw):
            call_log.append("engine_factory")
            return engine

        def mock_stage_wrapper(eng, ctx):
            call_log.append("stage_wrapper")
            return Mock()

        desc = _make_descriptor(
            engine_factory=mock_engine_factory,
            stage_wrapper=mock_stage_wrapper,
        )
        factory = StageFactory()
        factory.register(desc)
        factory.create("test_stage", Mock(), _make_context())

        assert call_log == ["engine_factory", "stage_wrapper"]


class TestStageFactoryFailFast:

    def test_missing_capability_raises_before_engine_factory(self):
        """required_capabilities checked BEFORE engine_factory is called."""
        engine_factory = Mock()
        desc = _make_descriptor(
            engine_factory=engine_factory,
            required_capabilities=frozenset({_StubPort}),
        )
        factory = StageFactory()
        factory.register(desc)

        ctx = _make_context(capabilities={})

        with pytest.raises(MissingCapabilityError) as exc_info:
            factory.create("test_stage", Mock(), ctx)

        assert exc_info.value.port_type is _StubPort
        engine_factory.assert_not_called()

    def test_satisfied_capabilities_allow_creation(self):
        engine_factory = Mock(return_value=Mock())
        stage_wrapper = Mock(return_value=Mock())
        desc = _make_descriptor(
            engine_factory=engine_factory,
            stage_wrapper=stage_wrapper,
            required_capabilities=frozenset({_StubPort}),
        )
        factory = StageFactory()
        factory.register(desc)

        port_impl = Mock(spec=_StubPort)
        ctx = _make_context(capabilities={_StubPort: port_impl})

        result = factory.create("test_stage", Mock(), ctx)

        engine_factory.assert_called_once()
        assert result is stage_wrapper.return_value

    def test_multiple_required_capabilities_all_checked(self):
        engine_factory = Mock()
        desc = _make_descriptor(
            engine_factory=engine_factory,
            required_capabilities=frozenset({_StubPort, _AnotherPort}),
        )
        factory = StageFactory()
        factory.register(desc)

        # Only one of two capabilities provided
        ctx = _make_context(capabilities={_StubPort: Mock(spec=_StubPort)})

        with pytest.raises(MissingCapabilityError) as exc_info:
            factory.create("test_stage", Mock(), ctx)

        assert exc_info.value.port_type is _AnotherPort
        engine_factory.assert_not_called()


# ════════════════════════════════════════════════════════════════════════════════
# Integration: build_stage_factory()
# ════════════════════════════════════════════════════════════════════════════════

class TestBuildStageFactory:

    def test_all_6_stage_types_registered(self):
        from connector.delivery.cli.pipeline_registry import build_stage_factory

        factory = build_stage_factory()

        expected = {"map", "normalize", "enrich", "match", "resolve", "resolve_context"}
        assert set(factory.registered_types) == expected

    def test_resolve_context_create_raises_not_implemented(self):
        """resolve_context создаётся напрямую в PipelineContainer — create() не используется."""
        from connector.delivery.cli.pipeline_registry import build_stage_factory
        from unittest.mock import Mock
        from connector.domain.transform.context import StageExecutionContext, PipelineMetadata

        factory = build_stage_factory()
        catalog = Mock()
        metadata = PipelineMetadata(run_id="r", dataset_name="ds", catalog=catalog, sink_spec=None)
        ctx = StageExecutionContext(metadata=metadata, capabilities={})

        with pytest.raises(NotImplementedError):
            factory.create("resolve_context", Mock(), ctx)

