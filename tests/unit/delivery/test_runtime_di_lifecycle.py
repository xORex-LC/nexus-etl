"""
Unit-тесты lifecycle DI в delivery runtime.

Проверяют:
1. Устойчивость run_with_report/run_without_report при сбоях teardown/finalize.
2. Маппинг ошибок в _initialize_container_resources().
3. Правило сохранения первичного результата при вторичной ошибке teardown.
"""

from __future__ import annotations

import logging
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
import typer

from connector.common.observability import ServiceComponent
from connector.config.models import AppConfig
from connector.delivery.cli.context import CommandContext, UnboundCommandContext
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli import runtime as runtime_module
from connector.domain.reporting.sink import NullReportSink, ReportSink
from connector.domain.reporting.context import InMemoryReportContext
from connector.domain.reporting.assembler import ReportAssembler
from connector.domain.reporting.events import AddItemEvent
from connector.domain.diagnostics import build_catalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.dsl.issues import DslLoadError
from connector.domain.secrets.errors import SecretKeyConfigError


@dataclass
class _OverrideProbe:
    value: object | None = None

    def override(self, value: object) -> None:
        self.value = value


class _FakeContainer:
    def __init__(
        self,
        *,
        shutdown_exc: Exception | None = None,
        shutdown_failures: dict[str, Exception] | None = None,
        ledger_exc: Exception | None = None,
    ) -> None:
        self._shutdown_exc = shutdown_exc
        self._shutdown_failures = shutdown_failures or {}
        self._ledger_exc = ledger_exc
        self.shutdown_calls: list[str] = []
        self.app_config = _OverrideProbe()
        self.target = SimpleNamespace(transport=_OverrideProbe())
        self.target.shutdown_resources = lambda: self._shutdown_resources("target")
        self.dictionary = SimpleNamespace(
            shutdown_resources=lambda: self._shutdown_resources("dictionary")
        )
        self.cache = SimpleNamespace(
            shutdown_resources=lambda: self._shutdown_resources("cache")
        )
        self.sqlite = SimpleNamespace(
            shutdown_resources=lambda: self._shutdown_resources("sqlite")
        )
        self.observability = SimpleNamespace(
            ledger_backend=lambda: SimpleNamespace(append=self._append_ledger),
            pointer_publisher=lambda: SimpleNamespace(publish=lambda **_: None),
        )

    def _shutdown_resources(self, name: str) -> None:
        self.shutdown_calls.append(name)
        specific_exc = self._shutdown_failures.get(name)
        if specific_exc is not None:
            raise specific_exc
        if self._shutdown_exc is not None:
            raise self._shutdown_exc

    def _append_ledger(self, **_: object) -> None:
        if self._ledger_exc is not None:
            raise self._ledger_exc


@dataclass(frozen=True)
class _FakeObservabilitySession:
    component: ServiceComponent
    layout: object
    runtime: object
    logger: object
    log_file_path: str | None


class _NoopLogger:
    def debug(self, _event: str, **_fields: object) -> None:
        return None

    def info(self, _event: str, **_fields: object) -> None:
        return None

    def warning(self, _event: str, **_fields: object) -> None:
        return None

    def error(self, _event: str, **_fields: object) -> None:
        return None

    def critical(self, _event: str, **_fields: object) -> None:
        return None


def _patch_fake_observability(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Подменить observability session без реального DI/runtime wiring."""
    session = _FakeObservabilitySession(
        component=ServiceComponent.MAPPER,
        layout=object(),
        runtime=SimpleNamespace(
            redaction_engine=SimpleNamespace(redact_text=lambda value: value)
        ),
        logger=_NoopLogger(),
        log_file_path=str(tmp_path / "logs" / "mapping.log"),
    )
    monkeypatch.setattr(
        runtime_module.runtime_orchestrator,
        "_initialize_observability_session",
        lambda **_: session,
    )
    monkeypatch.setattr(
        runtime_module.runtime_orchestrator,
        "_run_observability_sweeper",
        lambda **_: None,
    )


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
            "dataset": {"dataset_name": "employees"},
            "execution": {"dry_run": True},
            "refresh": {"page_size": 100, "max_pages": 1},
            "matching_runtime": {
                "match_batch_size": 100,
                "match_flush_interval_ms": 100,
            },
            "resolver": {"resolve_batch_size": 100, "resolve_flush_interval_ms": 100},
        }
    )


def _ctx(tmp_path: Path) -> UnboundCommandContext:
    return CommandContext(
        logger=logging.getLogger("runtime-di-lifecycle-test"),
        run_id="test-run",
        catalog=build_catalog(None, strict=True),
        strict=True,
        app_config=_app_config(tmp_path),
        container=None,
    )


def _result_with(code: SystemErrorCode) -> CommandResult:
    result = CommandResult()
    result.add_code(code)
    return result


def test_run_with_report_restores_streams_when_shutdown_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    fake = _FakeContainer(shutdown_exc=RuntimeError("shutdown failed"))
    _patch_fake_observability(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(
        runtime_module, "_initialize_container_resources", lambda **_: None
    )
    monkeypatch.setattr(runtime_module, "_finalize_report_artifacts", lambda **_: None)

    original_stdout = sys.stdout
    original_stderr = sys.stderr

    with pytest.raises(typer.Exit) as exc_info:
        runtime_module.run_with_report(
            ctx=_ctx(tmp_path),
            command_name="mapping",
            opts=SimpleNamespace(),
            handler=lambda _ctx, _opts, _report: None,
            requirements=Requirements(),
        )

    assert exc_info.value.exit_code == 2
    assert sys.stdout is original_stdout
    assert sys.stderr is original_stderr


def test_run_with_report_keeps_primary_result_when_shutdown_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    fake = _FakeContainer(shutdown_exc=RuntimeError("shutdown failed"))
    _patch_fake_observability(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(
        runtime_module, "_initialize_container_resources", lambda **_: None
    )
    monkeypatch.setattr(runtime_module, "_finalize_report_artifacts", lambda **_: None)

    with pytest.raises(typer.Exit) as exc_info:
        runtime_module.run_with_report(
            ctx=_ctx(tmp_path),
            command_name="mapping",
            opts=SimpleNamespace(),
            handler=lambda _ctx, _opts, _report: _result_with(SystemErrorCode.OK),
            requirements=Requirements(),
        )

    # Первичный результат остаётся OK (ошибка shutdown считается вторичной).
    assert exc_info.value.exit_code == 0


def test_shutdown_container_resources_continues_after_first_failure() -> None:
    fake = _FakeContainer(shutdown_failures={"target": RuntimeError("target failed")})

    result = runtime_module._shutdown_container_resources(
        container=fake,  # type: ignore[arg-type]
        logger=_NoopLogger(),
        run_id="r-shutdown-continue",
        emit_user_error=False,
    )

    assert result is not None
    assert isinstance(result, CommandResult)
    assert result.system_codes == {SystemErrorCode.INTERNAL_ERROR}
    assert fake.shutdown_calls == ["target", "dictionary", "cache", "sqlite"]


def test_run_with_report_sets_internal_error_on_finalize_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    fake = _FakeContainer()
    _patch_fake_observability(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(
        runtime_module, "_initialize_container_resources", lambda **_: None
    )
    monkeypatch.setattr(
        runtime_module, "_shutdown_container_resources", lambda **_: None
    )
    monkeypatch.setattr(
        runtime_module,
        "_finalize_report_artifacts",
        lambda **_: _result_with(SystemErrorCode.INTERNAL_ERROR),
    )

    with pytest.raises(typer.Exit) as exc_info:
        runtime_module.run_with_report(
            ctx=_ctx(tmp_path),
            command_name="mapping",
            opts=SimpleNamespace(),
            handler=lambda _ctx, _opts, _report: None,
            requirements=Requirements(),
        )

    assert exc_info.value.exit_code == 2


def test_run_with_report_keeps_success_when_ledger_append_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    fake = _FakeContainer(ledger_exc=RuntimeError("ledger failed"))
    _patch_fake_observability(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(
        runtime_module, "_initialize_container_resources", lambda **_: None
    )
    monkeypatch.setattr(
        runtime_module, "_shutdown_container_resources", lambda **_: None
    )
    monkeypatch.setattr(runtime_module, "_finalize_report_artifacts", lambda **_: None)

    with pytest.raises(typer.Exit) as exc_info:
        runtime_module.run_with_report(
            ctx=_ctx(tmp_path),
            command_name="mapping",
            opts=SimpleNamespace(),
            handler=lambda _ctx, _opts, _report: _result_with(SystemErrorCode.OK),
            requirements=Requirements(),
        )

    assert exc_info.value.exit_code == 0


def test_run_with_report_finalizes_before_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = _FakeContainer()
    _patch_fake_observability(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(
        runtime_module, "_initialize_container_resources", lambda **_: None
    )
    events: list[str] = []

    def _finalize(**_kwargs):
        events.append("finalize")
        return None

    def _shutdown(**_kwargs):
        events.append("shutdown")
        return None

    monkeypatch.setattr(runtime_module, "_finalize_report_artifacts", _finalize)
    monkeypatch.setattr(runtime_module, "_shutdown_container_resources", _shutdown)
    monkeypatch.setattr(
        runtime_module.runtime_orchestrator,
        "_publish_latest_artifact_pointers_for_report",
        lambda **_: None,
    )
    monkeypatch.setattr(
        runtime_module.runtime_orchestrator,
        "_record_run_ledger_for_report",
        lambda **_: None,
    )

    runtime_module.run_with_report(
        ctx=_ctx(tmp_path),
        command_name="mapping",
        opts=SimpleNamespace(),
        handler=lambda _ctx, _opts, _report: None,
        requirements=Requirements(),
    )

    assert events == ["shutdown", "finalize"]


def test_run_with_report_uses_fallback_observability_layout_when_session_init_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = _FakeContainer()
    captured: dict[str, object] = {}

    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(
        runtime_module.runtime_orchestrator,
        "_initialize_observability_session",
        lambda **_: (_ for _ in ()).throw(RuntimeError("log-dir unavailable")),
    )
    monkeypatch.setattr(
        runtime_module.runtime_orchestrator,
        "_publish_latest_artifact_pointers_for_report",
        lambda **_: None,
    )
    monkeypatch.setattr(
        runtime_module.runtime_orchestrator,
        "_record_run_ledger_for_report",
        lambda **_: None,
    )
    monkeypatch.setattr(
        runtime_module, "_initialize_container_resources", lambda **_: None
    )
    monkeypatch.setattr(
        runtime_module, "_shutdown_container_resources", lambda **_: None
    )

    def _finalize(**kwargs):
        captured["layout"] = kwargs["layout"]
        captured["component"] = kwargs["component"]
        return None

    monkeypatch.setattr(runtime_module, "_finalize_report_artifacts", _finalize)

    with pytest.raises(typer.Exit) as exc_info:
        runtime_module.run_with_report(
            ctx=_ctx(tmp_path),
            command_name="mapping",
            opts=SimpleNamespace(),
            handler=lambda _ctx, _opts, _report: None,
            requirements=Requirements(),
        )

    assert exc_info.value.exit_code == 2
    assert captured["component"] == ServiceComponent.MAPPER
    assert captured["layout"] is not None


def test_run_without_report_sets_internal_error_on_teardown_only_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    fake = _FakeContainer(shutdown_exc=RuntimeError("shutdown failed"))
    _patch_fake_observability(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(
        runtime_module, "_initialize_container_resources", lambda **_: None
    )

    with pytest.raises(typer.Exit) as exc_info:
        runtime_module.run_without_report(
            ctx=_ctx(tmp_path),
            command_name="mapping",
            opts=SimpleNamespace(),
            handler=lambda _ctx, _opts, _report: None,
            requirements=Requirements(),
        )

    assert exc_info.value.exit_code == 2


def test_run_without_report_passes_null_report_sink_to_handler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = _FakeContainer()
    observed: dict[str, object] = {}

    _patch_fake_observability(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(
        runtime_module, "_initialize_container_resources", lambda **_: None
    )

    def _handler(_ctx, _opts, report_sink):
        observed["report_sink"] = report_sink
        return None

    runtime_module.run_without_report(
        ctx=_ctx(tmp_path),
        command_name="mapping",
        opts=SimpleNamespace(),
        handler=_handler,
        requirements=Requirements(),
    )

    assert isinstance(observed.get("report_sink"), NullReportSink)


def test_run_without_report_enforces_three_arg_handler_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    fake = _FakeContainer()
    _patch_fake_observability(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(
        runtime_module, "_initialize_container_resources", lambda **_: None
    )

    with pytest.raises(typer.Exit) as exc_info:
        runtime_module.run_without_report(
            ctx=_ctx(tmp_path),
            command_name="mapping",
            opts=SimpleNamespace(),
            handler=lambda _ctx, _opts: None,
            requirements=Requirements(),
        )

    assert exc_info.value.exit_code == 2


def test_initialize_container_resources_maps_sqlite_error(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        runtime_module,
        "_init_container_for_requirements",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            sqlite3.OperationalError("db is locked")
        ),
    )
    result = runtime_module._initialize_container_resources(
        container=object(),  # type: ignore[arg-type]
        requirements=Requirements(requires_cache=True),
        logger=_NoopLogger(),
        run_id="r1",
    )

    assert result is not None
    assert isinstance(result, CommandResult)
    assert result.system_codes == {SystemErrorCode.CACHE_ERROR}


def test_initialize_container_resources_maps_vault_domain_error(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        runtime_module,
        "_init_container_for_requirements",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(SecretKeyConfigError()),
    )
    result = runtime_module._initialize_container_resources(
        container=object(),  # type: ignore[arg-type]
        requirements=Requirements(),
        logger=_NoopLogger(),
        run_id="r2",
    )

    assert result is not None
    assert isinstance(result, CommandResult)
    assert result.system_codes == {SystemErrorCode.INTERNAL_ERROR}


def test_initialize_container_resources_maps_unknown_error(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        runtime_module,
        "_init_container_for_requirements",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    result = runtime_module._initialize_container_resources(
        container=object(),  # type: ignore[arg-type]
        requirements=Requirements(),
        logger=_NoopLogger(),
        run_id="r3",
    )

    assert result is not None
    assert isinstance(result, CommandResult)
    assert result.system_codes == {SystemErrorCode.INTERNAL_ERROR}


def test_initialize_container_resources_reraises_dsl_load_error_from_init_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        runtime_module,
        "_init_container_for_requirements",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            DslLoadError(
                code="DICT_RUNTIME_INIT_FAILED", message="dictionary init failed"
            )
        ),
    )

    with pytest.raises(DslLoadError) as exc_info:
        runtime_module._initialize_container_resources(
            container=object(),  # type: ignore[arg-type]
            requirements=Requirements(requires_dictionaries=True),
            logger=logging.getLogger("runtime-init-mapping-test"),
            run_id="r-dict",
        )

    assert exc_info.value.code == "DICT_RUNTIME_INIT_FAILED"


def test_apply_result_to_report_materializes_domain_error_without_diagnostics() -> None:
    context = InMemoryReportContext(run_id="r-apply-domain", command="mapping")
    sink = ReportSink(context)
    assembler = ReportAssembler(context=context)
    result = CommandResult()
    result.add_code(SystemErrorCode.INTERNAL_ERROR)

    runtime_module._apply_cli_result_to_report(
        sink,
        context,
        result,
        command_name="mapping",
        source="unit_test",
        secondary=False,
    )

    built = assembler.assemble()
    assert built.summary.rows_blocked == 1
    assert built.status == "FAILED"
    assert len(built.items) == 1
    assert built.items[0].diagnostics[0].code == "INTERNAL_ERROR"


def test_apply_result_to_report_skips_synthetic_when_failures_already_materialized() -> (
    None
):
    context = InMemoryReportContext(run_id="r-no-dup", command="mapping")
    sink = ReportSink(context)
    assembler = ReportAssembler(context=context)
    sink.emit(
        AddItemEvent(
            status="FAILED",
            row_ref=None,
            payload=None,
            errors=(),
            warnings=(),
            meta={"source": "existing"},
            store=True,
            preaggregated=False,
        )
    )
    result = CommandResult()
    result.add_code(SystemErrorCode.INTERNAL_ERROR)

    runtime_module._apply_cli_result_to_report(
        sink,
        context,
        result,
        command_name="mapping",
        source="unit_test",
        secondary=False,
    )

    built = assembler.assemble()
    assert built.summary.rows_total == 1
    assert len(built.items) == 1


def test_apply_result_to_report_downgrades_secondary_failure_to_warning() -> None:
    context = InMemoryReportContext(run_id="r-secondary", command="mapping")
    sink = ReportSink(context)
    assembler = ReportAssembler(context=context)
    result = CommandResult()
    result.add_code(SystemErrorCode.INTERNAL_ERROR)

    runtime_module._apply_cli_result_to_report(
        sink,
        context,
        result,
        command_name="mapping",
        source="runtime_shutdown",
        secondary=True,
    )

    built = assembler.assemble()
    assert built.summary.rows_blocked == 0
    assert built.summary.rows_passed == 1
    assert len(built.items) == 1
    assert built.items[0].status == "OK"
    assert built.items[0].diagnostics[0].severity == "warning"


def test_apply_result_to_report_rejects_non_domain_result() -> None:
    context = InMemoryReportContext(run_id="r-adapter", command="mapping")
    sink = ReportSink(context)

    with pytest.raises(TypeError):
        runtime_module._apply_cli_result_to_report(
            sink,
            context,
            2,
            command_name="mapping",
            source="unit_test",
            secondary=False,
        )


def test_exit_code_from_result_supports_only_canonical_path() -> None:
    canonical_ok = CommandResult()
    canonical_ok.add_code(SystemErrorCode.OK)
    canonical_fail = CommandResult()
    canonical_fail.add_code(SystemErrorCode.INTERNAL_ERROR)

    assert runtime_module._exit_code_from_result(canonical_ok) == 0
    assert runtime_module._exit_code_from_result(canonical_fail) == 2
    with pytest.raises(TypeError):
        runtime_module._exit_code_from_result(3)


def test_run_with_report_materializes_init_failure_into_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    def _capture_finalize(**kwargs):
        captured["report_assembler"] = kwargs["report_assembler"]
        return None

    fake = _FakeContainer()
    _patch_fake_observability(monkeypatch, tmp_path)
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(
        runtime_module,
        "_initialize_container_resources",
        lambda **_: _result_with(SystemErrorCode.CACHE_ERROR),
    )
    monkeypatch.setattr(runtime_module, "_finalize_report_artifacts", _capture_finalize)

    with pytest.raises(typer.Exit) as exc_info:
        runtime_module.run_with_report(
            ctx=_ctx(tmp_path),
            command_name="mapping",
            opts=SimpleNamespace(),
            handler=lambda _ctx, _opts, _report: _result_with(SystemErrorCode.OK),
            requirements=Requirements(),
        )

    assert exc_info.value.exit_code == 2
    assembler = captured["report_assembler"]
    assert isinstance(assembler, ReportAssembler)
    built = assembler.assemble()
    assert built.summary.rows_blocked == 1
    assert len(built.items) == 1
    assert built.items[0].meta["source"] == "runtime_init"
