from __future__ import annotations

from unittest.mock import Mock

from connector.delivery.pipelines.planning_pipeline_hooks import PlanningPipelineHooks


def _make_hooks(**kwargs) -> PlanningPipelineHooks:
    pending_expiry = kwargs.get("pending_expiry", Mock())
    match_scope = kwargs.get("match_scope", Mock())
    return PlanningPipelineHooks(pending_expiry=pending_expiry, match_scope=match_scope)


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
    hooks = _make_hooks(pending_expiry=pending_expiry, match_scope=match_scope).plan_hooks()

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
