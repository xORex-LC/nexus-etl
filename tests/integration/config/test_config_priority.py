import httpx
from typer.testing import CliRunner
from connector.main import app
import connector.delivery.commands.check_api as check_api_command
from connector.config.config import loadSettings
from connector.infra.http.ankey_client import AnkeyApiClient

runner = CliRunner()

def test_priority_cli_over_env_over_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join([
            'host: "1.1.1.1"',
            "port: 1111",
            'api_username: "cfg_user"',
            'api_password: "cfg_pass"',
        ]),
        encoding="utf-8",
    )

    # ENV overrides config
    monkeypatch.setenv("ANKEY_API_HOST", "2.2.2.2")
    monkeypatch.setenv("ANKEY_API_PORT", "2222")
    monkeypatch.setenv("ANKEY_API_USERNAME", "env_user")
    monkeypatch.setenv("ANKEY_API_PASSWORD", "env_pass")

    # CLI overrides env
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"items": []}))
    captured: dict[str, object] = {}

    def factory(*args, **kwargs):
        kwargs["transport"] = transport
        captured["args"] = args
        captured["kwargs"] = kwargs
        return AnkeyApiClient(*args, **kwargs)

    # main.py no longer exposes AnkeyApiClient; patch delivery command directly
    monkeypatch.setattr(check_api_command, "AnkeyApiClient", factory)
    result = runner.invoke(
        app,
        ["--config", str(cfg), "--host", "3.3.3.3", "--port", "3333", "--api-username", "cli_user", "--api-password", "cli_pass", "check-api"],
    )
    assert result.exit_code == 0
    assert captured["kwargs"]["baseUrl"] == "https://3.3.3.3:3333"
    assert captured["kwargs"]["username"] == "cli_user"
    assert captured["kwargs"]["password"] == "cli_pass"


def test_batch_settings_priority_cli_over_env_over_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                "match_batch_size: 100",
                "match_flush_interval_ms: 200",
                "resolve_batch_size: 300",
                "resolve_flush_interval_ms: 400",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANKEY_MATCH_BATCH_SIZE", "101")
    monkeypatch.setenv("ANKEY_MATCH_FLUSH_INTERVAL_MS", "201")
    monkeypatch.setenv("ANKEY_RESOLVE_BATCH_SIZE", "301")
    monkeypatch.setenv("ANKEY_RESOLVE_FLUSH_INTERVAL_MS", "401")

    loaded = loadSettings(
        config_path=str(cfg),
        cli_overrides={
            "match_batch_size": 102,
            "match_flush_interval_ms": 202,
            "resolve_batch_size": 302,
            "resolve_flush_interval_ms": 402,
        },
    )

    assert loaded.settings.match_batch_size == 102
    assert loaded.settings.match_flush_interval_ms == 202
    assert loaded.settings.resolve_batch_size == 302
    assert loaded.settings.resolve_flush_interval_ms == 402
