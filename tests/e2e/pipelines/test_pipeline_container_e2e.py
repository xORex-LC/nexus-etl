"""
E2E tests for PipelineContainer full wiring (DEC-004).

Verifies that PipelineContainer produces working stages that can
process real CSV data through various pipeline configurations
using real EmployeesSpec, real cache, and real stage factory.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock

from connector.datasets.employees.spec import make_employees_spec
from connector.delivery.cli.containers import PipelineContainer
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.stages.stages import PipelineOrchestrator, StageContract
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


def _build_container(monkeypatch, csv_path: Path):
    monkeypatch.setenv("EMPLOYEES_SOURCE_PATH", str(csv_path))
    dataset_spec = make_employees_spec()
    catalog = build_catalog("employees", strict=False)
    cache_roles = _build_cache_roles()

    settings_mock = Mock()
    settings_mock.resolver = None

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
    return container, catalog


class TestPipelineContainerE2E:

    def test_normalize_pipeline_produces_results(self, tmp_path, monkeypatch):
        """map + normalize → produces transform results from real CSV."""
        csv_path = tmp_path / "employees.csv"
        _write_csv(csv_path, [
            ["1", "Ivanov Ivan", "iivanov", "iivanov@example.com", "", "IT Dept", "", "", "", ""],
            ["2", "Petrov Petr", "ppetrov", "ppetrov@example.com", "", "HR Dept", "", "", "", ""],
        ])
        container, catalog = _build_container(monkeypatch, csv_path)

        row_source = container.row_source()
        map_stage = container.map_stage()
        normalize_stage = container.normalize_stage()

        stage_pipeline = PipelineOrchestrator([map_stage, normalize_stage])
        extractor = Extractor(row_source, catalog=catalog)
        results = list(stage_pipeline.run(extractor.run()))

        assert len(results) == 2
        for result in results:
            assert result.row is not None

    def test_enrich_pipeline_with_mock_lookup(self, tmp_path, monkeypatch):
        """map + normalize + enrich → produces enriched results."""
        csv_path = tmp_path / "employees.csv"
        _write_csv(csv_path, [
            ["1", "Ivanov Ivan", "iivanov", "iivanov@example.com", "", "IT Dept", "", "", "", ""],
        ])
        container, catalog = _build_container(monkeypatch, csv_path)

        row_source = container.row_source()
        map_stage = container.map_stage()
        normalize_stage = container.normalize_stage()
        enrich_stage = container.enrich_stage()

        stage_pipeline = PipelineOrchestrator([map_stage, normalize_stage, enrich_stage])
        extractor = Extractor(row_source, catalog=catalog)
        results = list(stage_pipeline.run(extractor.run()))

        assert len(results) == 1

    def test_all_stages_satisfy_stage_contract(self, tmp_path, monkeypatch):
        """All stages produced by PipelineContainer implement StageContract."""
        csv_path = tmp_path / "employees.csv"
        _write_csv(csv_path, [
            ["1", "Test User", "tuser", "t@e.com", "", "IT", "", "", "", ""],
        ])
        container, catalog = _build_container(monkeypatch, csv_path)

        stages = [
            container.map_stage(),
            container.normalize_stage(),
            container.enrich_stage(),
            container.match_stage(),
            container.resolve_stage(),
        ]
        for stage in stages:
            assert isinstance(stage, StageContract), (
                f"{type(stage).__name__} does not satisfy StageContract"
            )

    def test_error_record_does_not_stop_pipeline(self, tmp_path, monkeypatch):
        """A row with errors (empty fields) doesn't stop the pipeline from processing others."""
        csv_path = tmp_path / "employees.csv"
        _write_csv(csv_path, [
            # First row: incomplete data (will produce errors)
            ["", "", "", "", "", "", "", "", "", ""],
            # Second row: valid data
            ["1", "Ivanov Ivan", "iivanov", "iivanov@example.com", "", "IT Dept", "", "", "", ""],
        ])
        container, catalog = _build_container(monkeypatch, csv_path)

        row_source = container.row_source()
        stage_pipeline = PipelineOrchestrator([container.map_stage(), container.normalize_stage()])
        extractor = Extractor(row_source, catalog=catalog)
        results = list(stage_pipeline.run(extractor.run()))

        # Both rows produce results (even if one has errors)
        assert len(results) == 2

    def test_partial_consumption_cleanup(self, tmp_path, monkeypatch):
        """Partially consuming and closing the pipeline generator doesn't raise."""
        csv_path = tmp_path / "employees.csv"
        _write_csv(csv_path, [
            ["1", "Ivanov Ivan", "iivanov", "i@e.com", "", "IT", "", "", "", ""],
            ["2", "Petrov Petr", "ppetrov", "p@e.com", "", "HR", "", "", "", ""],
            ["3", "Sidorov Sid", "ssidorov", "s@e.com", "", "QA", "", "", "", ""],
        ])
        container, catalog = _build_container(monkeypatch, csv_path)

        row_source = container.row_source()
        stage_pipeline = PipelineOrchestrator([container.map_stage(), container.normalize_stage()])
        extractor = Extractor(row_source, catalog=catalog)
        gen = iter(stage_pipeline.run(extractor.run()))

        # Consume only 1 of 3 results
        first = next(gen)
        assert first is not None

        # Close without consuming rest — must not raise
        gen.close()
