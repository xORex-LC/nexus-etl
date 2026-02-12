from __future__ import annotations

import logging
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
    PendingSettings,
    RefreshSettings,
)
from connector.config.config import SettingsIssue, SettingsParseError
from connector.delivery.cli.context import CommandContext
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli.runtime import run_without_report
from connector.domain.diagnostics import build_catalog


def test_run_without_report_handles_settings_load_error(tmp_path) -> None:
    app_settings = AppSettings(
        api=ApiSettings(
            host=None,
            port=None,
            username=None,
            password=None,
            tls_skip_verify=False,
            ca_file=None,
            timeout_seconds=20.0,
            retries=3,
            retry_backoff_seconds=0.5,
            resource_exists_retries=3,
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
            report_items_limit=200,
            report_include_skipped=True,
            diagnostics_strict=False,
        ),
        dataset=DatasetSettings(
            dataset_name="employees",
            csv_has_header=False,
            include_deleted=False,
        ),
        execution=ExecutionSettings(
            stop_on_first_error=False,
            max_actions=None,
            dry_run=False,
        ),
        refresh=RefreshSettings(
            page_size=200,
            max_pages=None,
        ),
        matching_runtime=MatchingRuntimeSettings(
            match_batch_size=500,
            match_flush_interval_ms=500,
            resolve_batch_size=500,
            resolve_flush_interval_ms=500,
        ),
        pending=PendingSettings(
            pending_ttl_seconds=120,
            pending_max_attempts=5,
            pending_sweep_interval_seconds=60,
            pending_on_expire="error",
            pending_allow_partial=False,
            pending_retention_days=14,
        ),
    )
    ctx = CommandContext(
        logger=logging.getLogger("settings-boundary-test"),
        run_id="test-run",
        catalog=build_catalog(None, strict=True),
        strict=True,
        app_settings=app_settings,
    )

    def handler(_ctx, _opts):
        raise SettingsParseError(
            "invalid settings",
            [
                SettingsIssue(
                    code="settings.parse.invalid_value",
                    field_path="retries",
                    source="cli",
                    raw_value="bad",
                    message="invalid int",
                    hint="use integer",
                )
            ],
        )

    with pytest.raises(typer.Exit) as exc_info:
        run_without_report(
            ctx=ctx,
            command_name="mapping",
            opts=SimpleNamespace(),
            handler=handler,
            requirements=Requirements(),
        )

    assert exc_info.value.exit_code == 1
