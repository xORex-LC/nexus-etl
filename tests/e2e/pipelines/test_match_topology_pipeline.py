from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from connector.config.models import AppConfig
from connector.config.projections import to_cache_db_config
from connector.infra.cache.backends.sqlite.schema import ensure_cache_ready
from connector.infra.cache.dsl_runtime import load_cache_dsl_runtime
from connector.infra.cache.repository.cache_repository import SqliteCacheRepository
from connector.infra.sqlite.engine import open_sqlite
from connector.main import app
from tests.runtime_test_support import (
    latest_report_path,
    tracked_employees_runtime_roots,
    write_runtime_config,
)

pytestmark = pytest.mark.e2e

runner = CliRunner()

_HEADER = (
    "id",
    "name",
    "parent_id",
    "level_1_name",
    "level_2_name",
    "level_3_name",
)


def _write_organizations_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        handle.write(";".join(_HEADER) + "\n")
        for row in rows:
            handle.write(";".join(row.get(column, "") for column in _HEADER) + "\n")


def _app_config(tmp_path: Path) -> AppConfig:
    return AppConfig.model_validate(
        {
            "api": {
                "host": "http://localhost",
                "port": 443,
                "username": "u",
                "password": "p",
                "retries": 1,
                "retry_backoff_seconds": 0.1,
                "resource_exists_retries": 1,
            },
            "paths": {
                "cache_dir": str(tmp_path / "cache"),
                "log_dir": str(tmp_path / "logs"),
                "report_dir": str(tmp_path / "reports"),
            },
            "observability": {
                "logging": {"level": "INFO"},
                "reporting": {"items_limit": 100},
                "diagnostics": {"strict": True},
            },
            "dataset": {"dataset_name": "organizations"},
            "execution": {"dry_run": True},
            "refresh": {"page_size": 100, "max_pages": 1},
            "matching_runtime": {
                "match_batch_size": 100,
                "match_flush_interval_ms": 100,
            },
            "resolver": {
                "resolve_batch_size": 100,
                "resolve_flush_interval_ms": 100,
            },
        }
    )


def _build_repo(tmp_path: Path) -> SqliteCacheRepository:
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    db_path = str(cache_dir / "ankey_cache.sqlite3")
    engine = open_sqlite(to_cache_db_config(_app_config(tmp_path)), db_path)
    cache_specs = list(load_cache_dsl_runtime().cache_specs)
    ensure_cache_ready(engine, cache_specs)
    return SqliteCacheRepository(engine, cache_specs)


def _seed_organizations_topology(tmp_path: Path) -> None:
    repo = _build_repo(tmp_path)
    with repo.engine.transaction():
        repo.upsert(
            "organizations",
            {
                "_id": "org-root",
                "_ouid": 10,
                "code": "10",
                "name": "Head Office",
                "match_key": "10",
                "parent_id": None,
                "updated_at": "2026-06-01T00:00:00+00:00",
            },
        )
        repo.upsert(
            "organizations",
            {
                "_id": "org-branch-a",
                "_ouid": 20,
                "code": "20",
                "name": "Branch A",
                "match_key": "20",
                "parent_id": 10,
                "updated_at": "2026-06-01T00:00:00+00:00",
            },
        )
        repo.upsert(
            "organizations",
            {
                "_id": "org-branch-b",
                "_ouid": 30,
                "code": "30",
                "name": "Branch B",
                "match_key": "30",
                "parent_id": 10,
                "updated_at": "2026-06-01T00:00:00+00:00",
            },
        )
        repo.upsert(
            "organizations",
            {
                "_id": "org-a",
                "_ouid": 100,
                "code": "A-100",
                "name": "Shared team",
                "match_key": "A-100",
                "parent_id": 20,
                "updated_at": "2026-06-01T00:00:00+00:00",
            },
        )
        repo.upsert(
            "organizations",
            {
                "_id": "org-b",
                "_ouid": 200,
                "code": "B-200",
                "name": "Shared team",
                "match_key": "B-200",
                "parent_id": 30,
                "updated_at": "2026-06-01T00:00:00+00:00",
            },
        )
        repo.set_meta("organizations", "cache_snapshot_revision", "rev-42")
    repo.engine.close()


def _write_runtime_config(tmp_path: Path, source_dir: Path) -> Path:
    roots = tracked_employees_runtime_roots()
    return write_runtime_config(
        tmp_path,
        registry_path=roots["registry_path"],
        datasets_root=roots["datasets_root"],
        source_data_root=source_dir,
        source_projection_root=roots["source_projection_root"],
        target_projection_root=roots["target_projection_root"],
        dictionary_specs_root=roots["dictionary_specs_root"],
        dictionary_data_root=roots["dictionary_data_root"],
        cache_dir=tmp_path / "cache",
        log_dir=tmp_path / "logs",
        report_dir=tmp_path / "reports",
    )


def _write_path_columns_topology_fixture() -> None:
    topology_path = (
        tracked_employees_runtime_roots()["datasets_root"]
        / "organizations"
        / "organizations.topology.yaml"
    )
    topology_path.write_text(
        """
dataset: organizations
topology:
  canonicalization:
    ops:
      - op: trim
      - op: lower
      - op: regex_replace
        pattern: '\\s+'
        repl: " "
      - op: compact
  source:
    mode: path_columns
    path_columns:
      - field: level_1_name
      - field: level_2_name
      - field: level_3_name
  target:
    mode: adjacency_list
    node_id_field: _ouid
    parent_id_field: parent_id
    target_label_field: name
    payload_target_id_field: _id
""".lstrip(),
        encoding="utf-8",
    )


def test_match_command_disambiguates_duplicate_leaf_by_topology(tmp_path: Path) -> None:
    _write_path_columns_topology_fixture()
    _seed_organizations_topology(tmp_path)
    source_dir = tmp_path / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    _write_organizations_csv(
        source_dir / "source_departments.csv",
        [
            {
                "id": "SRC-001",
                "name": "Shared team",
                "parent_id": "20",
                "level_1_name": "Head Office",
                "level_2_name": "Branch A",
                "level_3_name": "Shared Team",
            },
            {
                "id": "SRC-002",
                "name": "Shared team",
                "parent_id": "30",
                "level_1_name": "Head Office",
                "level_2_name": "Branch B",
                "level_3_name": "Shared Team",
            },
        ],
    )

    config_path = _write_runtime_config(tmp_path, source_dir)
    result = runner.invoke(
        app,
        [
            "--config",
            str(config_path),
            "--run-id",
            "org-match",
            "match",
            "--dataset",
            "organizations",
            "--include-matched-items",
        ],
    )

    assert result.exit_code == 0
    report = json.loads(
        latest_report_path(tmp_path / "reports", "match").read_text(encoding="utf-8")
    )
    assert report["context"]["topology"]["status"] == "ok"
    assert report["context"]["match"]["topology"]["enabled"] is True
    assert report["context"]["match"]["topology"]["by_mode"] == {
        "exact_canonical_path": 2
    }

    payloads = [item["payload"] for item in report["items"]]
    selected_ids = [
        payload["match_decision"]["selected"]["target_id"] for payload in payloads
    ]
    assert selected_ids == ["org-a", "org-b"]
    assert all(
        payload["match_decision"]["reason_code"] == "topology_exact_canonical_path"
        for payload in payloads
    )


def test_match_command_reports_missing_topology_locator_as_row_failure(
    tmp_path: Path,
) -> None:
    _write_path_columns_topology_fixture()
    _seed_organizations_topology(tmp_path)
    source_dir = tmp_path / "sources"
    source_dir.mkdir(parents=True, exist_ok=True)
    _write_organizations_csv(
        source_dir / "source_departments.csv",
        [
            {
                "id": "SRC-001",
                "name": "Shared team",
                "parent_id": "20",
                "level_1_name": "",
                "level_2_name": "",
                "level_3_name": "",
            }
        ],
    )

    config_path = _write_runtime_config(tmp_path, source_dir)
    result = runner.invoke(
        app,
        [
            "--config",
            str(config_path),
            "--run-id",
            "org-plan",
            "match",
            "--dataset",
            "organizations",
            "--include-matched-items",
        ],
    )

    assert result.exit_code != 0
    report = json.loads(
        latest_report_path(tmp_path / "reports", "match").read_text(encoding="utf-8")
    )

    assert report["context"]["topology"]["status"] == "ok"
    assert report["context"]["topology"]["built_sides"] == ["target"]
    assert report["context"]["match"]["match_failed"] == 1
    assert report["items"][0]["diagnostics"][0]["code"] == "TOPOLOGY_SOURCE_PATH_EMPTY"
