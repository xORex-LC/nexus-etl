"""
E2E tests for PipelineContainer full wiring (DEC-004).

Verifies that PipelineContainer produces working stages that can
process real CSV data through various pipeline configurations
using real EmployeesSpec, real cache, and real stage factory.
"""

from __future__ import annotations

from pathlib import Path

from connector.config.models import AppConfig
from connector.common.runtime_paths import RuntimePathOverrides
from connector.datasets.registry import get_spec
from connector.delivery.cli.containers import PipelineContainer
from connector.domain.dependency_tree import TopologySnapshot
from connector.domain.dsl.loader import configure_runtime_paths
from connector.domain.diagnostics.catalog import build_catalog
from connector.domain.ports.topology import TopologyRuntimeRequirements
from connector.usecases.topology_bootstrap import StaticTopologyProvider
from connector.domain.transform.core.extractor import Extractor
from connector.domain.transform.core.iterators import iter_ok
from connector.domain.transform.stages.stages import PipelineOrchestrator, StageContract
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.infra.cache.dsl_runtime import load_cache_dsl_runtime
from connector.infra.cache.roles import build_sqlite_cache_role_ports
from connector.infra.identity.sqlite.schema import ensure_identity_schema
from connector.infra.sqlite.config import SqliteDbConfig
from connector.infra.sqlite.engine import open_sqlite
from tests.runtime_test_support import prepare_tracked_employees_source_file, tracked_employees_runtime_roots


HEADER = ";".join(
    [
        "Таб.№",
        "Пользователи",
        "Орг. единица уровня 1",
        "Орг. единица уровня 2",
        "Орг. единица уровня 3",
        "Орг. единица уровня 4",
        "Орг. единица уровня 5",
        "Организационная единица",
        "Штатная должность",
        "Поступл.",
        "Contract Number",
        "Догвр:нач.",
        "Название руководящей должности",
        "ДатаРожд",
        "Пол",
    ]
)


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
        lines.append(";".join(row))
    path.write_text("\n".join(lines), encoding="utf-8")


def _build_container(csv_path: Path):
    runtime_csv_path = prepare_tracked_employees_source_file(csv_path)
    roots = tracked_employees_runtime_roots()
    configure_runtime_paths(
        RuntimePathOverrides(
            datasets_root=roots["datasets_root"],
            dictionary_specs_root=roots["dictionary_specs_root"],
            dictionary_data_root=roots["dictionary_data_root"],
            source_data_root=runtime_csv_path.parent,
            source_projection_root=roots["source_projection_root"],
            target_projection_root=roots["target_projection_root"],
        )
    )
    dataset_spec = get_spec("employees")
    catalog = build_catalog("employees", strict=False)
    cache_roles = _build_cache_roles()

    container = PipelineContainer()
    container.cache_roles.override(cache_roles)
    container.app_config.override(AppConfig())
    container.dataset_spec.override(dataset_spec)
    container.run_id.override("e2e-test-run")
    container.catalog.override(catalog)
    container.include_deleted.override(False)
    container.secret_store.override(None)
    container.dictionaries.override(None)
    # employees.resolve.yaml включает topology_link → resolve_stage требует
    # активированных topology requirements + provider (в проде их даёт pre-handler
    # bootstrap). Подаём явные composition inputs, как handler.
    container.topology_requirements.override(
        TopologyRuntimeRequirements(
            pipeline_dataset="employees",
            topology_dataset="organizations",
            requires_source_topology=False,
            requires_target_topology=True,
            activation_sources=("resolve",),
        )
    )
    container.topology_provider.override(
        StaticTopologyProvider(source_snapshot=None, target_snapshot=TopologySnapshot.empty())
    )
    return container, catalog


class TestPipelineContainerE2E:

    def test_normalize_pipeline_produces_results(self, tmp_path):
        """map + normalize → produces transform results from real CSV."""
        csv_path = tmp_path / "employees.csv"
        _write_csv(csv_path, [
            ["1", "Ivanov Ivan Ivanovich", "", "", "", "", "", "IT Dept", "Engineer", "", "+111", "", "", "", ""],
            ["2", "Petrov Petr Petrovich", "", "", "", "", "", "HR Dept", "Analyst", "", "+222", "", "", "", ""],
        ])
        container, catalog = _build_container(csv_path)

        row_source = container.row_source()
        map_stage = container.map_stage()
        normalize_stage = container.normalize_stage()

        stage_pipeline = PipelineOrchestrator([map_stage, normalize_stage])
        extractor = Extractor(row_source, catalog=catalog)
        results = list(stage_pipeline.run(extractor.run()))

        assert len(results) == 2
        for result in results:
            assert result.row is not None

    def test_enrich_pipeline_with_mock_lookup(self, tmp_path):
        """map + normalize + enrich → produces enriched results."""
        csv_path = tmp_path / "employees.csv"
        _write_csv(csv_path, [
            ["1", "Ivanov Ivan Ivanovich", "", "", "", "", "", "IT Dept", "Engineer", "", "+111", "", "", "", ""],
        ])
        container, catalog = _build_container(csv_path)

        row_source = container.row_source()
        map_stage = container.map_stage()
        normalize_stage = container.normalize_stage()
        enrich_stage = container.enrich_stage()

        stage_pipeline = PipelineOrchestrator([map_stage, normalize_stage, enrich_stage])
        extractor = Extractor(row_source, catalog=catalog)
        results = list(stage_pipeline.run(extractor.run()))

        assert len(results) == 1

    def test_all_stages_satisfy_stage_contract(self, tmp_path):
        """All stages produced by PipelineContainer implement StageContract."""
        csv_path = tmp_path / "employees.csv"
        _write_csv(csv_path, [
            ["1", "Test User Tester", "", "", "", "", "", "IT", "Engineer", "", "+111", "", "", "", ""],
        ])
        container, catalog = _build_container(csv_path)

        stages = [
            container.map_stage(),
            container.normalize_stage(),
            container.enrich_stage(),
            container.match_stage(),
            container.resolve_context_stage(),
            container.resolve_stage(),
        ]
        for stage in stages:
            assert isinstance(stage, StageContract), (
                f"{type(stage).__name__} does not satisfy StageContract"
            )

    def test_error_record_does_not_stop_pipeline(self, tmp_path):
        """A row with errors (empty fields) doesn't stop the pipeline from processing others."""
        csv_path = tmp_path / "employees.csv"
        _write_csv(csv_path, [
            # First row: incomplete data (will produce errors)
            ["", "", "", "", "", "", "", "", "", "", "", "", "", "", ""],
            # Second row: valid data
            ["1", "Ivanov Ivan Ivanovich", "", "", "", "", "", "IT Dept", "Engineer", "", "+111", "", "", "", ""],
        ])
        container, catalog = _build_container(csv_path)

        row_source = container.row_source()
        stage_pipeline = PipelineOrchestrator([container.map_stage(), container.normalize_stage()])
        extractor = Extractor(row_source, catalog=catalog)
        results = list(stage_pipeline.run(extractor.run()))

        # Both rows produce results (even if one has errors)
        assert len(results) == 2

    def test_partial_consumption_cleanup(self, tmp_path):
        """Partially consuming and closing the pipeline generator doesn't raise."""
        csv_path = tmp_path / "employees.csv"
        _write_csv(csv_path, [
            ["1", "Ivanov Ivan Ivanovich", "", "", "", "", "", "IT", "Engineer", "", "+111", "", "", "", ""],
            ["2", "Petrov Petr Petrovich", "", "", "", "", "", "HR", "Analyst", "", "+222", "", "", "", ""],
            ["3", "Sidorov Sid Sidorovich", "", "", "", "", "", "QA", "QA Lead", "", "+333", "", "", "", ""],
        ])
        container, catalog = _build_container(csv_path)

        row_source = container.row_source()
        stage_pipeline = PipelineOrchestrator([container.map_stage(), container.normalize_stage()])
        extractor = Extractor(row_source, catalog=catalog)
        gen = iter(stage_pipeline.run(extractor.run()))

        # Consume only 1 of 3 results
        first = next(gen)
        assert first is not None

        # Close without consuming rest — must not raise
        gen.close()
