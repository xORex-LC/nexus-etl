from __future__ import annotations

from typer.testing import CliRunner

from connector.main import app


runner = CliRunner()


def test_app_callback_handles_settings_load_error_for_bad_config_path(tmp_path) -> None:
    missing_cfg = tmp_path / "missing.yml"

    result = runner.invoke(app, ["--config", str(missing_cfg), "check-api"])

    assert result.exit_code == 2
    assert "invalid settings configuration" in result.output
    assert "settings.source.config_read_failed" in result.output
