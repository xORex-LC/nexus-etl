from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from connector.common.observability import (
    ComponentIdentity,
    ObservabilityLayout,
    ObservabilityLayoutPolicy,
    ServiceComponent,
    component_for_command,
)
from connector.common.runtime_paths import RuntimePathOverrides, detect_runtime_paths


def _write(path: Path, content: str = "datasets: {}\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _runtime_paths(tmp_path: Path):
    runtime_root = tmp_path / "runtime"
    _write(runtime_root / "datasets" / "registry.yaml")
    return detect_runtime_paths(
        overrides=RuntimePathOverrides(runtime_root=runtime_root),
        argv0="/ignored/bin/nexus",
        module_file=tmp_path / "src" / "module.py",
    )


def test_observability_layout_uses_component_partition_and_utc_names(tmp_path: Path) -> None:
    layout = ObservabilityLayout(
        runtime_paths=_runtime_paths(tmp_path),
        policy=ObservabilityLayoutPolicy(partition_by_component=True, clock="utc"),
    )
    now = datetime(2026, 6, 4, 12, 30, 15, tzinfo=timezone.utc)

    assert layout.log_file(ServiceComponent.ENRICHER, now=now) == (
        tmp_path / "runtime" / "var" / "logs" / "enricher" / "2026-06-04_enricher.log"
    )
    assert layout.report_file(ServiceComponent.ENRICHER, now=now) == (
        tmp_path / "runtime" / "reports" / "enricher" / "2026-06-04T12-30-15_enricher.json"
    )
    assert layout.plan_file(ServiceComponent.ENRICHER, now=now) == (
        tmp_path / "runtime" / "var" / "plans" / "enricher" / "2026-06-04T12-30-15_enricher.json"
    )


def test_observability_layout_without_partition_keeps_roots_flat(tmp_path: Path) -> None:
    layout = ObservabilityLayout(
        runtime_paths=_runtime_paths(tmp_path),
        policy=ObservabilityLayoutPolicy(partition_by_component=False, clock="utc"),
    )
    now = datetime(2026, 6, 4, 12, 30, 15, tzinfo=timezone.utc)

    assert layout.log_file(ServiceComponent.PLANNER, now=now) == (
        tmp_path / "runtime" / "var" / "logs" / "2026-06-04_planner.log"
    )


def test_observability_layout_converts_aware_local_time_to_utc_name(tmp_path: Path) -> None:
    layout = ObservabilityLayout(
        runtime_paths=_runtime_paths(tmp_path),
        policy=ObservabilityLayoutPolicy(partition_by_component=True, clock="utc"),
    )
    local_now = datetime(2026, 6, 4, 20, 30, 15, tzinfo=timezone(timedelta(hours=8)))

    assert layout.report_file(ServiceComponent.PLANNER, now=local_now).name == (
        "2026-06-04T12-30-15_planner.json"
    )


def test_observability_layout_accepts_component_identity(tmp_path: Path) -> None:
    layout = ObservabilityLayout(runtime_paths=_runtime_paths(tmp_path))
    now = datetime(2026, 6, 4, 12, 30, 15, tzinfo=timezone.utc)
    identity = ComponentIdentity(component=ServiceComponent.CACHE)

    assert layout.log_file(identity, now=now).name == "2026-06-04_cache.log"


def test_component_for_command_covers_current_command_surface() -> None:
    assert component_for_command("mapping") is ServiceComponent.MAPPER
    assert component_for_command("normalize") is ServiceComponent.NORMALIZER
    assert component_for_command("enrich") is ServiceComponent.ENRICHER
    assert component_for_command("match") is ServiceComponent.MATCHER
    assert component_for_command("resolve") is ServiceComponent.RESOLVER
    assert component_for_command("import-plan") is ServiceComponent.PLANNER
    assert component_for_command("import_apply") is ServiceComponent.APPLIER
    assert component_for_command("cache-refresh") is ServiceComponent.CACHE
    assert component_for_command("vault-status") is ServiceComponent.VAULT
    assert component_for_command("check-api") is ServiceComponent.TOPOLOGY
