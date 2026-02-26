from __future__ import annotations

import logging
from types import SimpleNamespace

import pytest
import typer

from connector.config.models import AppConfig
from connector.config.config import SettingsIssue, SettingsLoadError
from connector.delivery.cli.context import CommandContext
from connector.delivery.cli.requirements import Requirements
from connector.delivery.cli.runtime import run_without_report
from connector.domain.diagnostics import build_catalog


def test_run_without_report_handles_settings_load_error(tmp_path) -> None:
    app_config = AppConfig.model_validate({
        "paths": {
            "cache_dir": str(tmp_path / "cache"),
            "log_dir": str(tmp_path / "logs"),
            "report_dir": str(tmp_path / "reports"),
        }
    })
    ctx = CommandContext(
        logger=logging.getLogger("settings-boundary-test"),
        run_id="test-run",
        catalog=build_catalog(None, strict=True),
        strict=True,
        app_config=app_config,
        container=None,
    )

    def handler(_ctx, _opts):
        raise SettingsLoadError(
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
