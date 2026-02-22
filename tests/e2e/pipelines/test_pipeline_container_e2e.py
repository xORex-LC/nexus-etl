"""
E2E test for PipelineContainer full wiring (DEC-004 Stage 4).

Verifies that PipelineContainer produces working stages that can
process real CSV data through the normalize pipeline (map → normalize)
using real EmployeesSpec, real cache, and real stage factory.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import Mock

from connector.datasets.employees.spec import make_employees_spec
from connector.delivery.cli.containers import PipelineContainer
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.stages.stages import StagePipeline
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.cache.dsl_runtime import load_cache_dsl_runtime
from connector.infra.cache.roles import build_sqlite_cache_role_ports
from connector.infra.identity.sqlite.schema import ensure_identity_schema
from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.sqlite.engine import open_sqlite


HEADER = "raw_id,full_name,login,email_or_phone,contacts,org,manager,flags,employment,extra"


def _make_engine():
    return open_sqlite(SqliteDbConfig(transaction_mode="deferred"), ":memory:")


def _build_cache_roles():
    cache_specs = list(load_cache_dsl_runtime().cache_specs)
    cache_engine = _make_engine()
    identity_engine = _make_engine()
    ensure_identity_schema(identity_engine)
    gateway = SqliteCacheGateway.from_engine(
        cache_engine=cache_engine,
        identity_engine=identity_engine,
        cache_specs=cache_specs,
    )
    return build_sqlite_cache_role_ports(gateway)


def _write_csv(path: Path, rows: list[list[str]]) -> None:
    lines = [HEADER]
    for row in rows:
        lines.append(",".join(row))
    path.write_text("\n".join(lines), encoding="utf-8")


class TestPipelineContainerE2E:

    def test_normalize_pipeline_produces_results(self, tmp_path, monkeypatch):
        """
        Full wiring: PipelineContainer → map_stage + normalize_stage →
        StagePipeline → Extractor → produces transform results from real CSV.
        """
        # Prepare CSV with 2 employee rows
        csv_path = tmp_path / "employees.csv"
        _write_csv(csv_path, [
            ["1", "Ivanov Ivan", "iivanov", "iivanov@example.com", "", "IT Dept", "", "", "", ""],
            ["2", "Petrov Petr", "ppetrov", "ppetrov@example.com", "", "HR Dept", "", "", "", ""],
        ])
        monkeypatch.setenv("EMPLOYEES_SOURCE_PATH", str(csv_path))

        # Build real dependencies
        dataset_spec = make_employees_spec()
        catalog = build_catalog("employees", strict=False)
        cache_roles = _build_cache_roles()

        settings_mock = Mock()
        settings_mock.resolver = None

        # Assemble PipelineContainer with per-command overrides
        container = PipelineContainer()
        container.cache_roles.override(cache_roles)
        container.app_settings.override(settings_mock)
        container.dataset_spec.override(dataset_spec)
        container.run_id.override("e2e-test-run")
        container.csv_has_header.override(True)
        container.catalog.override(catalog)
        container.include_deleted.override(False)
        container.secret_store.override(None)
        container.dictionaries.override(None)

        # Get stages from container
        row_source = container.row_source()
        map_stage = container.map_stage()
        normalize_stage = container.normalize_stage()

        # Run the normalize pipeline
        stage_pipeline = StagePipeline([map_stage, normalize_stage])
        extractor = Extractor(row_source, catalog=catalog)
        results = list(stage_pipeline.run(extractor.run()))

        # Verify we got results for both rows
        assert len(results) == 2
        for result in results:
            assert result.row is not None
