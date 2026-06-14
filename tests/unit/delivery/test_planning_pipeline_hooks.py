from __future__ import annotations

from unittest.mock import Mock

import pytest

from connector.delivery.pipelines.planning_pipeline_hooks import PlanningPipelineHooks

pytestmark = pytest.mark.unit


def _make_hooks(**kwargs) -> PlanningPipelineHooks:
    pending_expiry = kwargs.get("pending_expiry", Mock())
    match_scope = kwargs.get("match_scope", Mock())
    pipeline_lifecycle = kwargs.get("pipeline_lifecycle")
    return PlanningPipelineHooks(
        pending_expiry=pending_expiry,
        match_scope=match_scope,
        pipeline_lifecycle=pipeline_lifecycle,
    )


def test_plan_hooks_calls_pending_expiry_sweep_on_resolve_stage_complete():
    pending_expiry = Mock()
    hooks = _make_hooks(pending_expiry=pending_expiry).plan_hooks()

    assert hooks.on_stage_complete is not None
    hooks.on_stage_complete("resolve", 12.5, {"items": 3})

    pending_expiry.sweep.assert_called_once_with()


def test_plan_hooks_calls_match_scope_clear_on_match_stage_complete():
    match_scope = Mock()
    hooks = _make_hooks(match_scope=match_scope).plan_hooks()

    assert hooks.on_stage_complete is not None
    hooks.on_stage_complete("match", 8.0, {"items": 5})

    match_scope.clear_scope.assert_called_once_with()


def test_plan_hooks_ignores_unknown_stage():
    pending_expiry = Mock()
    match_scope = Mock()
    hooks = _make_hooks(
        pending_expiry=pending_expiry, match_scope=match_scope
    ).plan_hooks()

    assert hooks.on_stage_complete is not None
    hooks.on_stage_complete("enrich", 12.5, {"items": 3})

    pending_expiry.sweep.assert_not_called()
    match_scope.clear_scope.assert_not_called()


def test_plan_hooks_resolve_does_not_trigger_match_scope():
    match_scope = Mock()
    hooks = _make_hooks(match_scope=match_scope).plan_hooks()

    hooks.on_stage_complete("resolve", 5.0, {"items": 2})

    match_scope.clear_scope.assert_not_called()


def test_plan_hooks_match_does_not_trigger_pending_expiry():
    pending_expiry = Mock()
    hooks = _make_hooks(pending_expiry=pending_expiry).plan_hooks()

    hooks.on_stage_complete("match", 5.0, {"items": 2})

    pending_expiry.sweep.assert_not_called()


def test_plan_hooks_emit_lifecycle_before_housekeeping_on_complete():
    calls: list[str] = []
    pending_expiry = Mock()
    pending_expiry.sweep.side_effect = lambda: calls.append("sweep")
    pipeline_lifecycle = Mock()
    pipeline_lifecycle.stage_completed.side_effect = lambda **_: calls.append(
        "lifecycle"
    )
    hooks = _make_hooks(
        pending_expiry=pending_expiry,
        pipeline_lifecycle=pipeline_lifecycle,
    ).plan_hooks()

    hooks.on_stage_complete("resolve", 2.5, {"items": 7})

    assert calls == ["lifecycle", "sweep"]
    pipeline_lifecycle.stage_completed.assert_called_once_with(
        stage_name="resolve",
        duration_ns=2_500_000,
        stats={"items": 7},
    )


def test_lifecycle_hooks_do_not_run_plan_housekeeping():
    pending_expiry = Mock()
    match_scope = Mock()
    pipeline_lifecycle = Mock()
    hooks = _make_hooks(
        pending_expiry=pending_expiry,
        match_scope=match_scope,
        pipeline_lifecycle=pipeline_lifecycle,
    ).lifecycle_hooks()

    hooks.on_stage_complete("resolve", 1.0, {"items": 1})
    hooks.on_stage_complete("match", 1.0, {"items": 1})

    pending_expiry.sweep.assert_not_called()
    match_scope.clear_scope.assert_not_called()
    assert pipeline_lifecycle.stage_completed.call_count == 2


def test_plan_hooks_forward_start_error_and_abort_lifecycle_events():
    pipeline_lifecycle = Mock()
    hooks = _make_hooks(pipeline_lifecycle=pipeline_lifecycle).plan_hooks()
    exc = RuntimeError("boom")

    hooks.on_stage_start("map")
    hooks.on_stage_error("map", exc, 3.0)
    hooks.on_stage_abort("map", 4.0)

    pipeline_lifecycle.stage_started.assert_called_once_with(stage_name="map")
    pipeline_lifecycle.stage_failed.assert_called_once_with(
        stage_name="map",
        exc=exc,
        duration_ns=3_000_000,
    )
    pipeline_lifecycle.stage_aborted.assert_called_once_with(
        stage_name="map",
        duration_ns=4_000_000,
    )
