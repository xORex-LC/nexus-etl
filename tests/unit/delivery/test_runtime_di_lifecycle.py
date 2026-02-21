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
from typing import Any

import pytest
import typer

from connector.config.app_settings import (
    ApiSettings,
    AppSettings,
    DatasetSettings,
    ExecutionSettings,
    MatchingRuntimeSettings,
    ObservabilitySettings,
    PathsSettings,
    RefreshSettings,
)
from connector.delivery.cli.context import CommandContext, UnboundCommandContext
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli import runtime as runtime_module
from connector.domain.diagnostics import build_catalog
from connector.domain.diagnostics.command_result import CommandResult
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.secrets.errors import SecretKeyConfigError
from connector.domain.transform.resolver.resolve_deps import ResolverSettings


@dataclass
class _OverrideProbe:
    value: object | None = None

    def override(self, value: object) -> None:
        self.value = value


class _FakeContainer:
    def __init__(self, *, shutdown_exc: Exception | None = None) -> None:
        self._shutdown_exc = shutdown_exc
        self.app_settings = _OverrideProbe()
        self.target = SimpleNamespace(transport=_OverrideProbe())

    def shutdown_resources(self) -> None:
        if self._shutdown_exc is not None:
            raise self._shutdown_exc


def _app_settings(tmp_path: Path) -> AppSettings:
    return AppSettings(
        api=ApiSettings(
            host="http://localhost",
            port=443,
            username="u",
            password="p",
            tls_skip_verify=False,
            ca_file=None,
            timeout_seconds=20.0,
            retries=1,
            retry_backoff_seconds=0.1,
            resource_exists_retries=1,
        ),
        paths=PathsSettings(
            cache_dir=str(tmp_path / "cache"),
            log_dir=str(tmp_path / "logs"),
            report_dir=str(tmp_path / "reports"),
        ),
        observability=ObservabilitySettings(
            log_level="INFO",
            log_json=False,
            report_format="json",
            report_items_limit=100,
            report_include_skipped=True,
            diagnostics_strict=True,
        ),
        dataset=DatasetSettings(
            dataset_name="employees",
            csv_has_header=True,
            include_deleted=False,
        ),
        execution=ExecutionSettings(
            stop_on_first_error=False,
            max_actions=None,
            dry_run=True,
        ),
        refresh=RefreshSettings(page_size=100, max_pages=1),
        matching_runtime=MatchingRuntimeSettings(
            match_batch_size=100,
            match_flush_interval_ms=100,
            resolve_batch_size=100,
            resolve_flush_interval_ms=100,
        ),
        resolver=ResolverSettings(
            pending_ttl_seconds=120,
            pending_max_attempts=5,
            pending_sweep_interval_seconds=60,
            pending_on_expire="error",
            pending_allow_partial=False,
            pending_retention_days=14,
        ),
    )


def _ctx(tmp_path: Path) -> UnboundCommandContext:
    return CommandContext(
        logger=logging.getLogger("runtime-di-lifecycle-test"),
        run_id="test-run",
        catalog=build_catalog(None, strict=True),
        strict=True,
        app_settings=_app_settings(tmp_path),
        container=None,
    )


def _result_with(code: SystemErrorCode) -> CommandResult:
    result = CommandResult()
    result.add_code(code)
    return result


def test_run_with_report_restores_streams_when_shutdown_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    fake = _FakeContainer(shutdown_exc=RuntimeError("shutdown failed"))
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(runtime_module, "_initialize_container_resources", lambda **_: None)
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
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(runtime_module, "_initialize_container_resources", lambda **_: None)
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


def test_run_with_report_sets_internal_error_on_finalize_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    fake = _FakeContainer()
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(runtime_module, "_initialize_container_resources", lambda **_: None)
    monkeypatch.setattr(runtime_module, "_shutdown_container_resources", lambda **_: None)
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


def test_run_without_report_sets_internal_error_on_teardown_only_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    fake = _FakeContainer(shutdown_exc=RuntimeError("shutdown failed"))
    monkeypatch.setattr(runtime_module, "AppContainer", lambda: fake)
    monkeypatch.setattr(runtime_module, "_initialize_container_resources", lambda **_: None)

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
        lambda *_args, **_kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("db is locked")),
    )
    result = runtime_module._initialize_container_resources(
        container=object(),  # type: ignore[arg-type]
        requirements=Requirements(requires_cache=True),
        logger=logging.getLogger("runtime-init-mapping-test"),
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
        logger=logging.getLogger("runtime-init-mapping-test"),
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
        logger=logging.getLogger("runtime-init-mapping-test"),
        run_id="r3",
    )

    assert result is not None
    assert isinstance(result, CommandResult)
    assert result.system_codes == {SystemErrorCode.INTERNAL_ERROR}
