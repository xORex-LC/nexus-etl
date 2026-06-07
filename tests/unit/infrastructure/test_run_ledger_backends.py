"""Юнит-тесты run ledger backends и их retention-seams."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from connector.common.observability import (
    ObservabilityArtifactKind,
    ObservabilityLayout,
    ObservabilityLayoutPolicy,
    ServiceComponent,
)
from connector.common.runtime_paths import RuntimePathOverrides, detect_runtime_paths
from connector.config.models import AppConfig
from connector.config.projections import to_cache_db_config
from connector.infra.observability.ledger import (
    JsonlRunLedger,
    SqliteRunLedger,
    build_run_ledger_record,
)
from connector.infra.observability.viewer import ObservabilityArtifactViewer

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


def _app_config(tmp_path: Path, *, backend: str = "jsonl") -> AppConfig:
    return AppConfig.model_validate(
        {
            "paths": {
                "cache_dir": str(tmp_path / "var" / "cache"),
                "log_dir": str(tmp_path / "var" / "logs"),
                "report_dir": str(tmp_path / "reports"),
                "plans_dir": str(tmp_path / "var" / "plans"),
            },
            "observability": {
                "ledger": {"backend": backend},
            },
        }
    )


def _record(component: ServiceComponent, run_id: str = "run-1"):
    return build_run_ledger_record(
        run_id=run_id,
        pipeline_run_id=f"{run_id}-pipeline",
        component=component,
        started_at="2026-06-05T10:00:00+00:00",
        finished_at="2026-06-05T10:01:00+00:00",
        status="SUCCESS",
        log_path="/tmp/log.log",
        report_path="/tmp/report.json",
        plan_path="/tmp/plan.json",
    )


def test_jsonl_ledger_appends_one_line_per_run(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    ledger = JsonlRunLedger(layout=layout)

    ledger.append(
        component=ServiceComponent.PLANNER,
        record=_record(ServiceComponent.PLANNER, "run-1"),
    )
    ledger.append(
        component=ServiceComponent.PLANNER,
        record=_record(ServiceComponent.PLANNER, "run-2"),
    )

    ledger_path = layout.ledger_file(ServiceComponent.PLANNER, backend="jsonl")
    lines = ledger_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    payload = json.loads(lines[-1])
    assert payload["run_id"] == "run-2"
    assert payload["component"] == "planner"
    assert payload["row_counters"]["rows_total"] == 0

    latest = ledger.latest_record(component=ServiceComponent.PLANNER)
    assert latest is not None
    assert latest.run_id == "run-2"


def test_jsonl_ledger_prune_keeps_recent_entries(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    ledger = JsonlRunLedger(layout=layout)
    ledger_path = layout.ledger_file(ServiceComponent.ENRICHER, backend="jsonl")
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "run_id": "old",
                        "pipeline_run_id": "old",
                        "component": "enricher",
                        "started_at": "2026-05-01T10:00:00+00:00",
                        "finished_at": "2026-05-01T10:01:00+00:00",
                        "status": "SUCCESS",
                        "row_counters": {},
                        "log_path": None,
                        "report_path": None,
                        "plan_path": None,
                    }
                ),
                json.dumps(
                    {
                        "run_id": "fresh",
                        "pipeline_run_id": "fresh",
                        "component": "enricher",
                        "started_at": "2026-06-05T10:00:00+00:00",
                        "finished_at": "2026-06-05T10:01:00+00:00",
                        "status": "SUCCESS",
                        "row_counters": {},
                        "log_path": None,
                        "report_path": None,
                        "plan_path": None,
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    ledger.prune(
        component=ServiceComponent.ENRICHER,
        retention_days=7,
        now=datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc),
    )

    payloads = [
        json.loads(line)
        for line in ledger_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item["run_id"] for item in payloads] == ["fresh"]


def test_sqlite_ledger_persists_record(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    ledger = SqliteRunLedger(
        layout=layout,
        sqlite_config=to_cache_db_config(_app_config(tmp_path, backend="sqlite")),
    )

    ledger.append(
        component=ServiceComponent.APPLIER, record=_record(ServiceComponent.APPLIER)
    )

    ledger_path = layout.ledger_file(ServiceComponent.APPLIER, backend="sqlite")
    with sqlite3.connect(ledger_path) as conn:
        row = conn.execute(
            "SELECT run_id, pipeline_run_id, component, status FROM run_ledger"
        ).fetchone()

    assert row == ("run-1", "run-1-pipeline", "applier", "SUCCESS")
    latest = ledger.latest_record(component=ServiceComponent.APPLIER)
    assert latest is not None
    assert latest.run_id == "run-1"


def test_sqlite_ledger_prune_removes_old_rows(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    ledger = SqliteRunLedger(
        layout=layout,
        sqlite_config=to_cache_db_config(_app_config(tmp_path, backend="sqlite")),
    )
    old_record = build_run_ledger_record(
        run_id="old",
        pipeline_run_id="old",
        component=ServiceComponent.CACHE,
        started_at="2026-05-01T10:00:00+00:00",
        finished_at="2026-05-01T10:01:00+00:00",
        status="SUCCESS",
        log_path=None,
        report_path=None,
        plan_path=None,
    )
    fresh_record = build_run_ledger_record(
        run_id="fresh",
        pipeline_run_id="fresh",
        component=ServiceComponent.CACHE,
        started_at="2026-06-05T10:00:00+00:00",
        finished_at="2026-06-05T10:01:00+00:00",
        status="SUCCESS",
        log_path=None,
        report_path=None,
        plan_path=None,
    )
    ledger.append(component=ServiceComponent.CACHE, record=old_record)
    ledger.append(component=ServiceComponent.CACHE, record=fresh_record)

    ledger.prune(
        component=ServiceComponent.CACHE,
        retention_days=7,
        now=datetime(2026, 6, 5, 12, 0, tzinfo=timezone.utc),
    )

    ledger_path = layout.ledger_file(ServiceComponent.CACHE, backend="sqlite")
    with sqlite3.connect(ledger_path) as conn:
        rows = conn.execute("SELECT run_id FROM run_ledger ORDER BY id").fetchall()

    assert rows == [("fresh",)]


def test_artifact_viewer_reads_latest_artifact_from_ledger(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    ledger = JsonlRunLedger(layout=layout)
    report_path = tmp_path / "reports" / "planner" / "2026-06-05T10-01-00_planner.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text('{"status":"SUCCESS"}', encoding="utf-8")

    ledger.append(
        component=ServiceComponent.PLANNER,
        record=build_run_ledger_record(
            run_id="run-1",
            pipeline_run_id="run-1",
            component=ServiceComponent.PLANNER,
            started_at="2026-06-05T10:00:00+00:00",
            finished_at="2026-06-05T10:01:00+00:00",
            status="SUCCESS",
            log_path=None,
            report_path=str(report_path),
            plan_path=None,
        ),
    )

    viewer = ObservabilityArtifactViewer(ledger_backend=ledger)
    latest_path = viewer.resolve_latest_artifact_path(
        component=ServiceComponent.PLANNER,
        artifact_kind=ObservabilityArtifactKind.REPORT,
    )

    assert latest_path == report_path
    assert viewer.read_text(path=latest_path) == '{"status":"SUCCESS"}'
