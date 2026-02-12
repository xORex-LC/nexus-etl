from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import connector.delivery.commands.check_api as check_api_command
from connector.main import app


runner = CliRunner()


def test_check_api_smoke_works_with_slice_wiring(tmp_path: Path, monkeypatch) -> None:
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                'host: "1.1.1.1"',
                "port: 1111",
                'api_username: "cfg_user"',
                'api_password: "cfg_pass"',
            ]
        ),
        encoding="utf-8",
    )
    log_dir = tmp_path / "logs"
    report_dir = tmp_path / "reports"
    cache_dir = tmp_path / "cache"

    captured: dict[str, object] = {}

    class _Client:
        def getJson(self, *_args, **_kwargs):  # noqa: N802
            return {"items": []}

    def _build_api_client(api_settings, *, transport=None):
        captured["api_settings"] = api_settings
        captured["transport"] = transport
        return _Client()

    monkeypatch.setattr(check_api_command, "build_api_client", _build_api_client)

    result = runner.invoke(
        app,
        [
            "--config",
            str(cfg),
            "--log-dir",
            str(log_dir),
            "--report-dir",
            str(report_dir),
            "--cache-dir",
            str(cache_dir),
            "--host",
            "3.3.3.3",
            "--port",
            "3333",
            "--api-username",
            "cli_user",
            "--api-password",
            "cli_pass",
            "check-api",
        ],
    )

    assert result.exit_code == 0
    api_settings = captured["api_settings"]
    assert api_settings.host == "3.3.3.3"
    assert api_settings.port == 3333
    assert api_settings.username == "cli_user"
    assert api_settings.password == "cli_pass"


def test_mapping_reports_deterministic_settings_error_on_missing_config(tmp_path: Path) -> None:
    missing_cfg = tmp_path / "missing.yml"
    result = runner.invoke(app, ["--config", str(missing_cfg), "mapping"])

    assert result.exit_code == 2
    assert "invalid settings configuration" in result.output
    assert "settings.source.config_read_failed" in result.output
