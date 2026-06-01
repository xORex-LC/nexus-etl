"""Интеграционные тесты Stage D runtime bootstrap, short-circuit и provider wiring."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

from connector.config.models import AppConfig
from connector.delivery.cli import containers as containers_module
from connector.delivery.cli import runtime as runtime_module
from connector.delivery.cli.containers import _init_container_for_requirements, build_dataset_spec
from connector.delivery.cli.context import CommandContext, UnboundCommandContext
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli.runtime.topology_bootstrap import (
    TopologyBootstrapStep,
    _TopologyBootstrapConfigurationError,
    attach_topology_runtime,
)
from connector.delivery.commands.topology_runtime import pipeline_topology_scope
from connector.domain.diagnostics import build_catalog, build_error, build_warning
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.ports.topology import TopologyProviderPort, TopologyRuntimeRequirements
from connector.domain.models import DiagnosticStage
from connector.domain.reporting.assembler import ReportAssembler
from connector.domain.reporting.context import InMemoryReportContext
from connector.domain.reporting.sink import ReportSink
from connector.infra.cache.cache_gateway import SqliteCacheGateway
from connector.usecases.topology_bootstrap import (
    TopologyActivationDecision,
    TopologyBootstrapRequest,
    TopologyBootstrapResult,
)

pytestmark = pytest.mark.integration


def _app_config(tmp_path: Path, *, dataset_name: str = "employees") -> AppConfig:
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
                "log_level": "INFO",
                "report_items_limit": 100,
                "diagnostics_strict": True,
            },
            "dataset": {"dataset_name": dataset_name},
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


def _ctx(tmp_path: Path, *, dataset_name: str = "employees") -> UnboundCommandContext:
    return CommandContext(
        logger=logging.getLogger(f"topology-runtime-{dataset_name}"),
        run_id="integration-run",
        catalog=build_catalog(None, strict=True),
        strict=True,
        app_config=_app_config(tmp_path, dataset_name=dataset_name),
        container=None,
        extra={"quiet": True, "console_log_mirror": False, "sources": []},
    )


def test_run_with_report_short_circuits_on_required_topology_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    employees_registry_path,
) -> None:
    captured: dict[str, object] = {}
    handler_called = {"value": False}

    def _capture_finalize(**kwargs):
        captured["report_assembler"] = kwargs["report_assembler"]
        return None

    monkeypatch.setattr(runtime_module, "_finalize_report_artifacts", _capture_finalize)

    with pytest.raises(typer.Exit) as exc_info:
        runtime_module.run_with_report(
            ctx=_ctx(tmp_path, dataset_name="organizations"),
            command_name="match",
            opts=SimpleNamespace(dataset="organizations"),
            handler=lambda *_args, **_kwargs: handler_called.__setitem__("value", True),
            requirements=Requirements(
                requires_source=True,
                requires_dataset=True,
                requires_cache=True,
            ),
        )

    assert exc_info.value.exit_code == 2
    assert handler_called["value"] is False
    assembler = captured["report_assembler"]
    assert isinstance(assembler, ReportAssembler)
    envelope = assembler.assemble()
    assert envelope.context["topology"]["status"] == "error"
    assert envelope.context["topology"]["errors"] == 1
    assert any(
        diag.code == "TOPOLOGY_TARGET_EMPTY"
        for item in envelope.items
        for diag in item.diagnostics
    )


def test_run_with_report_skips_bootstrap_for_dataset_without_capability(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    employees_registry_path,
) -> None:
    captured: dict[str, object] = {}
    handler_called = {"value": False}

    def _capture_finalize(**kwargs):
        captured["report_assembler"] = kwargs["report_assembler"]
        return None

    monkeypatch.setattr(runtime_module, "_finalize_report_artifacts", _capture_finalize)

    with pytest.raises(typer.Exit) as exc_info:
        runtime_module.run_with_report(
            ctx=_ctx(tmp_path, dataset_name="employees"),
            command_name="match",
            opts=SimpleNamespace(dataset="employees"),
            handler=lambda _ctx, _opts, _report: (
                handler_called.__setitem__("value", True)
                or runtime_module._result_with(SystemErrorCode.OK)
            ),
            requirements=Requirements(
                requires_source=True,
                requires_dataset=True,
                requires_cache=True,
            ),
        )

    assert exc_info.value.exit_code == 0
    assert handler_called["value"] is True
    assembler = captured["report_assembler"]
    assert isinstance(assembler, ReportAssembler)
    envelope = assembler.assemble()
    assert envelope.context["topology"]["status"] == "skipped"
    assert envelope.context["topology"]["skip_reason"] == "capability_disabled"


def test_topology_provider_is_injected_into_planning_context(
    tmp_path: Path,
    employees_registry_path,
) -> None:
    app_config = _app_config(tmp_path, dataset_name="organizations")
    container = containers_module.AppContainer()
    container.app_config.override(app_config)
    _init_container_for_requirements(
        container,
        Requirements(requires_source=True, requires_dataset=True, requires_cache=True),
    )
    gateway = container.cache.gateway()
    assert isinstance(gateway, SqliteCacheGateway)

    with gateway.transaction():
        gateway.cache.upsert(
            "organizations",
            {
                "_id": "org-100",
                "_ouid": 100,
                "code": "100",
                "name": " Head Office ",
                "match_key": "100",
                "parent_id": None,
                "updated_at": "2026-06-01T11:00:00+00:00",
            },
        )
        gateway.cache.set_meta("organizations", "cache_snapshot_revision", "rev-42")

    report_context = InMemoryReportContext(
        run_id="integration-run",
        command="match",
    )
    step_result = TopologyBootstrapStep().run(
        ctx=_ctx(tmp_path, dataset_name="organizations"),
        command_name="match",
        dataset_name="organizations",
        requirements=Requirements(
            requires_source=True,
            requires_dataset=True,
            requires_cache=True,
        ),
        container=container,
        report_sink=ReportSink(report_context),
        logger=logging.getLogger("topology-bootstrap-step"),
        run_id="integration-run",
    )

    ctx = attach_topology_runtime(
        ctx=_ctx(tmp_path, dataset_name="organizations"),
        runtime_binding=step_result.runtime_binding,
    )
    dataset_name, dataset_spec = build_dataset_spec("organizations", app_config.dataset)
    catalog = containers_module.build_diagnostics_catalog(dataset_name, strict=True)
    pipeline = container.pipeline

    with pipeline_topology_scope(ctx=ctx, pipeline=pipeline), \
         pipeline.dataset_spec.override(dataset_spec), \
         pipeline.run_id.override("integration-run"), \
         pipeline.catalog.override(catalog):
        planning_context = pipeline.planning_context()

    provider = step_result.runtime_binding.provider
    assert step_result.command_result is None
    assert provider is not None
    assert planning_context.has(TopologyProviderPort) is True
    assert planning_context.require(TopologyProviderPort) is provider
    assert planning_context.has(TopologyRuntimeRequirements) is True
    assert planning_context.require(TopologyRuntimeRequirements).requires_target_topology is True
    assert hasattr(provider, "metadata") is False


def test_topology_step_short_circuit_keeps_warnings(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    employees_registry_path,
) -> None:
    import connector.delivery.cli.runtime.topology_bootstrap as step_module

    catalog = containers_module.build_diagnostics_catalog("organizations", strict=True)
    report_context = InMemoryReportContext(
        run_id="integration-run",
        command="match",
    )
    sink = ReportSink(report_context)

    error_diag = build_error(
        catalog=catalog,
        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
        code="TOPOLOGY_TARGET_EMPTY",
        message="empty target topology",
    )
    warning_diag = build_warning(
        catalog=catalog,
        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
        code="TOPOLOGY_SOURCE_PATH_MALFORMED",
        message="row path collapsed after normalization",
    )

    class _AlwaysActiveResolver:
        def resolve(self, *, command_name: str, dataset_name: str) -> TopologyActivationDecision:
            return TopologyActivationDecision(
                request=TopologyBootstrapRequest(
                    pipeline_dataset=dataset_name,
                    topology_dataset=None,
                    run_id="",
                    require_source_topology=False,
                    require_target_topology=True,
                ),
                capability_enabled=True,
                activation_sources=("match",),
                target_failure_is_hard=True,
            )

    class _FakeUseCase:
        def __init__(self, *args, **kwargs) -> None:
            pass

        def run(
            self,
            *,
            request: TopologyBootstrapRequest,
            target_failure_is_hard: bool,
        ) -> TopologyBootstrapResult:
            return TopologyBootstrapResult(
                artifacts=None,
                errors=(error_diag,),
                warnings=(warning_diag,),
            )

    monkeypatch.setattr(step_module, "TopologyBootstrapUseCase", _FakeUseCase)

    step_result = TopologyBootstrapStep(
        requirement_resolver=_AlwaysActiveResolver()
    ).run(
        ctx=_ctx(tmp_path, dataset_name="organizations"),
        command_name="match",
        dataset_name="organizations",
        requirements=Requirements(
            requires_source=True,
            requires_dataset=True,
            requires_cache=True,
        ),
        container=object(),
        report_sink=sink,
        logger=logging.getLogger("topology-short-circuit"),
        run_id="integration-run",
    )

    assert step_result.command_result is not None
    assert [diag.code for diag in step_result.command_result.diagnostics] == [
        "TOPOLOGY_TARGET_EMPTY",
        "TOPOLOGY_SOURCE_PATH_MALFORMED",
    ]


def test_topology_step_converts_missing_cache_spec_into_topology_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    employees_registry_path,
) -> None:
    import connector.delivery.cli.runtime.topology_bootstrap as step_module

    def _raise_config_error(*args, **kwargs):
        catalog = kwargs["catalog"]
        diagnostic = build_error(
            catalog=catalog,
            stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
            code="TOPOLOGY_TARGET_CACHE_SPEC_MISSING",
            message="missing cache spec",
        )
        raise _TopologyBootstrapConfigurationError(diagnostic=diagnostic)

    monkeypatch.setattr(step_module, "_build_target_usecase", _raise_config_error)

    report_context = InMemoryReportContext(
        run_id="integration-run",
        command="match",
    )
    sink = ReportSink(report_context)

    step_result = TopologyBootstrapStep().run(
        ctx=_ctx(tmp_path, dataset_name="organizations"),
        command_name="match",
        dataset_name="organizations",
        requirements=Requirements(
            requires_source=True,
            requires_dataset=True,
            requires_cache=True,
        ),
        container=object(),
        report_sink=sink,
        logger=logging.getLogger("topology-missing-cache-spec"),
        run_id="integration-run",
    )

    assert step_result.command_result is not None
    assert [diag.code for diag in step_result.command_result.diagnostics] == [
        "TOPOLOGY_TARGET_CACHE_SPEC_MISSING"
    ]
    assert report_context.snapshot().context["topology"]["status"] == "error"
