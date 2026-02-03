import httpx
from typer.testing import CliRunner
from connector.main import app
import connector.delivery.commands.check_api as check_api_command
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
