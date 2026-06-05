"""Юнит-тесты ретенции report/plan observability-артефактов."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from connector.common.observability import (
    ObservabilityLayout,
    ObservabilityLayoutPolicy,
    ServiceComponent,
)
from connector.common.runtime_paths import RuntimePathOverrides, detect_runtime_paths
from connector.infra.observability.retention import ObservabilityRetentionSweeper

pytestmark = pytest.mark.unit


def _layout(tmp_path: Path) -> ObservabilityLayout:
    return ObservabilityLayout(
        runtime_paths=detect_runtime_paths(
            overrides=RuntimePathOverrides(
                runtime_root=Path.cwd(),
                cache_root=tmp_path / "var" / "cache",
                logs_root=tmp_path / "var" / "logs",
                reports_root=tmp_path / "reports",
                plans_root=tmp_path / "var" / "plans",
            )
        ),
        policy=ObservabilityLayoutPolicy(partition_by_component=True, clock="utc"),
    )


def test_sweeper_removes_old_reports(tmp_path: Path) -> None:
    report_dir = tmp_path / "reports" / "planner"
    report_dir.mkdir(parents=True)
    old_report = report_dir / "2026-05-01T01-00-00_planner.json"
    fresh_report = report_dir / "2026-06-05T01-00-00_planner.json"
    old_report.write_text("{}", encoding="utf-8")
    fresh_report.write_text("{}", encoding="utf-8")

    sweeper = ObservabilityRetentionSweeper(layout=_layout(tmp_path))
    result = sweeper.sweep_reports(
        component=ServiceComponent.PLANNER,
        retention_days=7,
        now=datetime(2026, 6, 5, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert old_report in result.deleted_files
    assert not old_report.exists()
    assert fresh_report.exists()


def test_sweeper_removes_old_plans(tmp_path: Path) -> None:
    plan_dir = tmp_path / "var" / "plans" / "planner"
    plan_dir.mkdir(parents=True)
    old_plan = plan_dir / "2026-05-01T01-00-00_planner.json"
    fresh_plan = plan_dir / "2026-06-05T01-00-00_planner.json"
    old_plan.write_text("{}", encoding="utf-8")
    fresh_plan.write_text("{}", encoding="utf-8")

    sweeper = ObservabilityRetentionSweeper(layout=_layout(tmp_path))
    result = sweeper.sweep_plans(
        component=ServiceComponent.PLANNER,
        retention_days=7,
        now=datetime(2026, 6, 5, 1, 0, 0, tzinfo=timezone.utc),
    )

    assert old_plan in result.deleted_files
    assert not old_plan.exists()
    assert fresh_plan.exists()
