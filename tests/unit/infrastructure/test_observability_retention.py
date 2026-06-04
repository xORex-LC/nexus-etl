"""Юнит-тесты safe retention sweeper для observability-логов."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from connector.common.observability import ObservabilityLayout, ObservabilityLayoutPolicy, ServiceComponent
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
            ),
        ),
        policy=ObservabilityLayoutPolicy(partition_by_component=True, clock="utc"),
    )


def test_sweeper_removes_old_files_and_excess_backups(tmp_path: Path) -> None:
    component_dir = tmp_path / "var" / "logs" / "applier"
    component_dir.mkdir(parents=True)
    old_file = component_dir / "2026-05-01_applier.log"
    active = component_dir / "2026-06-04_applier.log"
    keep_backup = component_dir / "2026-06-04_applier.1.log"
    drop_backup = component_dir / "2026-06-04_applier.2.log"
    for path in (old_file, active, keep_backup, drop_backup):
        path.write_text(path.name, encoding="utf-8")

    sweeper = ObservabilityRetentionSweeper(layout=_layout(tmp_path))
    result = sweeper.sweep_logs(
        component=ServiceComponent.APPLIER,
        retention_days=7,
        retention_backups=1,
        now=datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc),
    )

    assert old_file in result.deleted_files
    assert drop_backup in result.deleted_files
    assert active.exists()
    assert keep_backup.exists()
    assert not old_file.exists()
    assert not drop_backup.exists()
    assert result.skipped_by_marker is False


def test_sweeper_skips_second_run_same_day_and_ignores_symlinks(tmp_path: Path) -> None:
    component_dir = tmp_path / "var" / "logs" / "planner"
    component_dir.mkdir(parents=True)
    target = component_dir / "2026-05-01_planner.log"
    target.write_text("old", encoding="utf-8")
    symlink = component_dir / "2026-04-01_planner.log"
    symlink.symlink_to(target)

    sweeper = ObservabilityRetentionSweeper(layout=_layout(tmp_path))
    now = datetime(2026, 6, 4, 10, 0, tzinfo=timezone.utc)
    first = sweeper.sweep_logs(
        component=ServiceComponent.PLANNER,
        retention_days=7,
        retention_backups=0,
        now=now,
    )
    second = sweeper.sweep_logs(
        component=ServiceComponent.PLANNER,
        retention_days=7,
        retention_backups=0,
        now=now,
    )

    assert target in first.deleted_files
    assert symlink.is_symlink()
    assert second.skipped_by_marker is True
