from __future__ import annotations

from unittest.mock import Mock

from connector.delivery.pipelines.planning_pipeline_hooks import PlanningPipelineHooks


def test_resolve_stage_hooks_calls_pending_expiry_sweep_on_stage_complete():
    pending_expiry = Mock()
    hooks = PlanningPipelineHooks(pending_expiry).resolve_stage_hooks()

    assert hooks.on_stage_complete is not None
    hooks.on_stage_complete("resolve", 12.5, {"items": 3})

    pending_expiry.sweep.assert_called_once_with()


def test_resolve_stage_hooks_ignores_non_resolve_stage():
    pending_expiry = Mock()
    hooks = PlanningPipelineHooks(pending_expiry).resolve_stage_hooks()

    assert hooks.on_stage_complete is not None
    hooks.on_stage_complete("match", 12.5, {"items": 3})

    pending_expiry.sweep.assert_not_called()
