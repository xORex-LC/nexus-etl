"""
Интеграционные тесты lifecycle DI для run_with_report.

Проверяют сценарий с реальным AppContainer, когда ошибка возникает
в teardown ресурса target.runtime.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace

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
from connector.delivery.cli import runtime as runtime_module
from connector.delivery.cli import containers as containers_module
from connector.delivery.cli.context import CommandContext, UnboundCommandContext
from connector.delivery.cli.requirements import Requirements
from connector.domain.diagnostics import build_catalog
from connector.domain.diagnostics.policies import SystemErrorCode
from connector.domain.transform.resolver.resolve_deps import ResolverSettings
from connector.infra.target.core.factory import TargetRuntimeBuildResult


class _RuntimeWithCloseFailure:
    def __init__(self, *, fail_on_close: bool) -> None:
        self.fail_on_close = fail_on_close
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1
        if self.fail_on_close:
            raise RuntimeError("target runtime close failed")


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
        logger=logging.getLogger("runtime-di-integration-test"),
        run_id="integration-run",
        catalog=build_catalog(None, strict=True),
        strict=True,
        app_settings=_app_settings(tmp_path),
        container=None,
    )


def _fake_target_runtime_builder(runtime: _RuntimeWithCloseFailure):
    def _build(*_args, **_kwargs) -> TargetRuntimeBuildResult:
        return TargetRuntimeBuildResult(
            runtime=runtime,  # type: ignore[arg-type]
            target_type="test",
            requested_mode="core",
            effective_mode="core",
        )

    return _build


def test_run_with_report_keeps_primary_result_on_target_runtime_teardown_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _RuntimeWithCloseFailure(fail_on_close=True)
    monkeypatch.setattr(
        containers_module,
        "build_target_runtime_with_info",
        _fake_target_runtime_builder(runtime),
    )

    with pytest.raises(typer.Exit) as exc_info:
        runtime_module.run_with_report(
            ctx=_ctx(tmp_path),
            command_name="mapping",
            opts=SimpleNamespace(),
            handler=lambda _ctx, _opts, _report: runtime_module._result_with(SystemErrorCode.OK),
            requirements=Requirements(requires_api=True),
        )

    assert exc_info.value.exit_code == 0
    assert runtime.close_calls == 1


def test_run_with_report_returns_internal_error_when_teardown_is_only_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    runtime = _RuntimeWithCloseFailure(fail_on_close=True)
    monkeypatch.setattr(
        containers_module,
        "build_target_runtime_with_info",
        _fake_target_runtime_builder(runtime),
    )

    with pytest.raises(typer.Exit) as exc_info:
        runtime_module.run_with_report(
            ctx=_ctx(tmp_path),
            command_name="mapping",
            opts=SimpleNamespace(),
            handler=lambda _ctx, _opts, _report: None,
            requirements=Requirements(requires_api=True),
        )

    assert exc_info.value.exit_code == 2
    assert runtime.close_calls == 1
