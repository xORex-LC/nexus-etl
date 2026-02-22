"""
Tests for StageExecutionContext, PipelineMetadata, and MissingCapabilityError (DEC-004 Stage 2).

Architecture:
    - PipelineMetadata is a frozen dataclass.
    - StageExecutionContext is immutable (no public setters for _capabilities).
    - Capability scoping: stages see only their own capabilities.

Unit:
    - require/get/has API contract.
    - Scoped contexts for enrich vs planning stages.
    - Cross-stage capability isolation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable
from unittest.mock import Mock

import pytest

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.transform.context import (
    MissingCapabilityError,
    PipelineMetadata,
    StageExecutionContext,
)


# ════════════════════════════════════════════════════════════════════════════════
# Test helpers / stub protocols
# ════════════════════════════════════════════════════════════════════════════════

@runtime_checkable
class _StubPortA(Protocol):
    def do_a(self) -> str: ...


@runtime_checkable
class _StubPortB(Protocol):
    def do_b(self) -> int: ...


@runtime_checkable
class _StubPortC(Protocol):
    def do_c(self) -> None: ...


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


# ════════════════════════════════════════════════════════════════════════════════
# Architecture tests
# ════════════════════════════════════════════════════════════════════════════════

class TestArchitecture:

    def test_pipeline_metadata_is_frozen_dataclass(self):
        meta = _make_metadata()
        with pytest.raises(AttributeError):
            meta.run_id = "changed"  # type: ignore[misc]

    def test_stage_execution_context_is_frozen(self):
        """StageExecutionContext has no public setters for _capabilities."""
        ctx = _make_context()
        assert not hasattr(ctx, "capabilities")
        assert not hasattr(ctx, "set_capability")
        assert not hasattr(ctx, "add_capability")
        # _capabilities is private — direct mutation is convention-enforced
        assert hasattr(ctx, "_capabilities")

    def test_defensive_copy_of_capabilities(self):
        """Mutating the original dict does not affect context."""
        port_a = Mock(spec=_StubPortA)
        caps: dict[type, object] = {_StubPortA: port_a}
        ctx = _make_context(capabilities=caps)

        # Mutate external dict
        caps[_StubPortB] = Mock(spec=_StubPortB)

        assert ctx.has(_StubPortA)
        assert not ctx.has(_StubPortB)


# ════════════════════════════════════════════════════════════════════════════════
# Unit tests: require / get / has
# ════════════════════════════════════════════════════════════════════════════════

class TestContextRequire:

    def test_require_returns_registered_capability(self):
        port_a = Mock(spec=_StubPortA)
        ctx = _make_context(capabilities={_StubPortA: port_a})

        result = ctx.require(_StubPortA)

        assert result is port_a

    def test_require_raises_missing_capability_error(self):
        port_a = Mock(spec=_StubPortA)
        ctx = _make_context(capabilities={_StubPortA: port_a})

        with pytest.raises(MissingCapabilityError) as exc_info:
            ctx.require(_StubPortB)

        err = exc_info.value
        assert err.port_type is _StubPortB
        assert _StubPortA in err.available
        assert "_StubPortB" in str(err)

    def test_require_with_empty_context(self):
        ctx = _make_context()

        with pytest.raises(MissingCapabilityError) as exc_info:
            ctx.require(_StubPortA)

        assert exc_info.value.available == []


class TestContextGet:

    def test_get_returns_registered_capability(self):
        port_a = Mock(spec=_StubPortA)
        ctx = _make_context(capabilities={_StubPortA: port_a})

        assert ctx.get(_StubPortA) is port_a

    def test_get_returns_none_for_missing(self):
        ctx = _make_context(capabilities={_StubPortA: Mock(spec=_StubPortA)})

        assert ctx.get(_StubPortB) is None


class TestContextHas:

    def test_has_returns_true_for_registered(self):
        ctx = _make_context(capabilities={_StubPortA: Mock(spec=_StubPortA)})

        assert ctx.has(_StubPortA) is True

    def test_has_returns_false_for_missing(self):
        ctx = _make_context(capabilities={_StubPortA: Mock(spec=_StubPortA)})

        assert ctx.has(_StubPortB) is False


# ════════════════════════════════════════════════════════════════════════════════
# Scoping tests
# ════════════════════════════════════════════════════════════════════════════════

class TestCapabilityScoping:

    def test_enrich_context_scoping(self):
        """Enrich context contains EnrichLookupPort; no PlanningRuntimePort."""
        from connector.domain.ports.cache.roles import EnrichLookupPort, PlanningRuntimePort

        enrich_lookup = Mock(spec=EnrichLookupPort)
        ctx = _make_context(capabilities={EnrichLookupPort: enrich_lookup})

        assert ctx.has(EnrichLookupPort)
        assert ctx.require(EnrichLookupPort) is enrich_lookup
        assert not ctx.has(PlanningRuntimePort)

    def test_planning_context_scoping(self):
        """Planning context contains PlanningRuntimePort + ResolverSettings; no DictionaryProviderPort."""
        from connector.domain.ports.cache.roles import PlanningRuntimePort
        from connector.domain.ports.transform.dictionaries import DictionaryProviderPort
        from connector.domain.transform.resolver.resolve_deps import ResolverSettings

        planning_rt = Mock(spec=PlanningRuntimePort)
        resolver_settings = ResolverSettings(
            pending_ttl_seconds=3600,
            pending_max_attempts=3,
            pending_sweep_interval_seconds=60,
            pending_on_expire="skip",
            pending_allow_partial=False,
            pending_retention_days=7,
        )
        ctx = _make_context(capabilities={
            PlanningRuntimePort: planning_rt,
            ResolverSettings: resolver_settings,
        })

        assert ctx.has(PlanningRuntimePort)
        assert ctx.require(PlanningRuntimePort) is planning_rt
        assert ctx.has(ResolverSettings)
        assert ctx.require(ResolverSettings) is resolver_settings
        assert not ctx.has(DictionaryProviderPort)

    def test_capabilities_not_visible_cross_stage(self):
        """Enrich ctx has no PlanningRuntimePort; transform ctx has no EnrichLookupPort."""
        from connector.domain.ports.cache.roles import EnrichLookupPort, PlanningRuntimePort

        enrich_ctx = _make_context(capabilities={
            EnrichLookupPort: Mock(spec=EnrichLookupPort),
        })
        planning_ctx = _make_context(capabilities={
            PlanningRuntimePort: Mock(spec=PlanningRuntimePort),
        })

        assert not enrich_ctx.has(PlanningRuntimePort)
        assert not planning_ctx.has(EnrichLookupPort)


# ════════════════════════════════════════════════════════════════════════════════
# Metadata access
# ════════════════════════════════════════════════════════════════════════════════

class TestMetadataAccess:

    def test_metadata_accessible_from_context(self):
        catalog = Mock(spec=ErrorCatalog)
        ctx = _make_context(
            run_id="run-42",
            dataset_name="employees",
            catalog=catalog,
        )

        assert ctx.metadata.run_id == "run-42"
        assert ctx.metadata.dataset_name == "employees"
        assert ctx.metadata.catalog is catalog
        assert ctx.metadata.sink_spec is None

    def test_metadata_shared_across_contexts(self):
        """Multiple contexts can share the same PipelineMetadata instance."""
        meta = _make_metadata(run_id="shared-run")
        ctx1 = StageExecutionContext(metadata=meta, capabilities={})
        ctx2 = StageExecutionContext(metadata=meta, capabilities={_StubPortA: Mock()})

        assert ctx1.metadata is ctx2.metadata
        assert ctx1.metadata.run_id == "shared-run"
