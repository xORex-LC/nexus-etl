from typer.testing import CliRunner
from connector.cli import app

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
    result = runner.invoke(
        app,
        ["--config", str(cfg), "--host", "3.3.3.3", "--port", "3333", "--api-username", "cli_user", "--api-password", "cli_pass", "check-api"],
    )
    assert result.exit_code == 0
    assert "host=3.3.3.3 port=3333 api_username=cli_user" in result.stdout
    assert "api_password=***" in result.stdout
