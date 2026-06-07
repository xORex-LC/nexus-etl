"""Юнит-тесты layout-aware writers для report и plan артефактов."""

from __future__ import annotations

import json
from pathlib import Path
from datetime import datetime, timezone

import pytest

from connector.common.observability import (
    ObservabilityLayout,
    ObservabilityLayoutPolicy,
    ServiceComponent,
)
from connector.common.runtime_paths import RuntimePathOverrides, detect_runtime_paths
from connector.domain.reporting.models import ReportEnvelope, ReportMeta, ReportSummary
from connector.infra.artifacts.plan_writer import write_plan_file_with_layout
from connector.infra.artifacts.report_renderer import JsonReportRenderer

pytestmark = pytest.mark.unit


def _layout(tmp_path: Path) -> ObservabilityLayout:
    runtime_paths = detect_runtime_paths(
        overrides=RuntimePathOverrides(
            runtime_root=Path.cwd(),
            cache_root=tmp_path / "var" / "cache",
            logs_root=tmp_path / "var" / "logs",
            reports_root=tmp_path / "reports",
            plans_root=tmp_path / "var" / "plans",
        )
    )
    return ObservabilityLayout(
        runtime_paths=runtime_paths,
        policy=ObservabilityLayoutPolicy(partition_by_component=True, clock="utc"),
    )


def _report_envelope() -> ReportEnvelope:
    return ReportEnvelope(
        status="SUCCESS",
        meta=ReportMeta(
            run_id="run-123",
            dataset="employees",
            command="import-plan",
            started_at="2026-06-05T00:00:00Z",
        ),
        summary=ReportSummary(rows_total=1, rows_passed=1),
        items=[],
        context={},
    )


def test_render_with_layout_writes_report_to_component_partition(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    report_path = JsonReportRenderer().render_with_layout(
        envelope=_report_envelope(),
        layout=layout,
        component=ServiceComponent.PLANNER,
        now=datetime(2026, 6, 5, 1, 2, 3, tzinfo=timezone.utc),
    )

    path = Path(report_path)
    assert path == tmp_path / "reports" / "planner" / "2026-06-05T01-02-03_planner.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["meta"]["run_id"] == "run-123"
    assert payload["meta"]["schema_version"] == "2.0"


def test_write_plan_file_with_layout_writes_into_plans_root(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    plan_path = write_plan_file_with_layout(
        plan_items=[
            {"row_id": "1", "op": "create", "target_id": "", "desired_state": {}}
        ],
        summary={"rows_total": 1, "planned_create": 1},
        meta={"dataset": "employees", "csv_path": "input.csv"},
        layout=layout,
        component=ServiceComponent.PLANNER,
        run_id="run-789",
        generated_at="2026-06-05T01:02:03Z",
        now=datetime(2026, 6, 5, 1, 2, 3, tzinfo=timezone.utc),
    )

    path = Path(plan_path)
    assert (
        path
        == tmp_path / "var" / "plans" / "planner" / "2026-06-05T01-02-03_planner.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["meta"]["run_id"] == "run-789"
    assert payload["meta"]["dataset"] == "employees"


@pytest.mark.parametrize(
    ("writer_name", "writer_call", "expected_target", "sentinel_payload"),
    [
        (
            "report",
            lambda layout, now: JsonReportRenderer().render_with_layout(
                envelope=_report_envelope(),
                layout=layout,
                component=ServiceComponent.PLANNER,
                now=now,
            ),
            lambda tmp_path: tmp_path
            / "reports"
            / "planner"
            / "2026-06-05T01-02-03_planner.json",
            {"meta": {"run_id": "old-report"}},
        ),
        (
            "plan",
            lambda layout, now: write_plan_file_with_layout(
                plan_items=[
                    {
                        "row_id": "1",
                        "op": "create",
                        "target_id": "",
                        "desired_state": {},
                    }
                ],
                summary={"rows_total": 1, "planned_create": 1},
                meta={"dataset": "employees"},
                layout=layout,
                component=ServiceComponent.PLANNER,
                run_id="run-999",
                generated_at="2026-06-05T01:02:03Z",
                now=now,
            ),
            lambda tmp_path: tmp_path
            / "var"
            / "plans"
            / "planner"
            / "2026-06-05T01-02-03_planner.json",
            {"meta": {"run_id": "old-plan"}},
        ),
    ],
)
def test_layout_aware_writers_are_atomic_on_replace_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    writer_name: str,
    writer_call,
    expected_target,
    sentinel_payload: dict[str, object],
) -> None:
    layout = _layout(tmp_path)
    now = datetime(2026, 6, 5, 1, 2, 3, tzinfo=timezone.utc)
    target_path = expected_target(tmp_path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(sentinel_payload), encoding="utf-8")

    def _fail_replace(_src: str | Path, _dst: str | Path) -> None:
        raise OSError(f"{writer_name} replace failed")

    monkeypatch.setattr(
        "connector.infra.artifacts._atomic_json.os.replace", _fail_replace
    )

    with pytest.raises(OSError, match="replace failed"):
        writer_call(layout, now)

    assert json.loads(target_path.read_text(encoding="utf-8")) == sentinel_payload
    assert list(target_path.parent.glob("*.tmp")) == []
