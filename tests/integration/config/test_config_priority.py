import httpx
from typer.testing import CliRunner
from connector.main import app
import connector.delivery.commands.check_api as check_api_command
from connector.config.app_settings import loadAppSettings
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
    monkeypatch.setenv("ANKEY_HOST", "2.2.2.2")
    monkeypatch.setenv("ANKEY_PORT", "2222")
    monkeypatch.setenv("ANKEY_API_USERNAME", "env_user")
    monkeypatch.setenv("ANKEY_API_PASSWORD", "env_pass")

    # CLI overrides env
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"items": []}))
    captured: dict[str, object] = {}

    def factory(*args, **kwargs):
        api_settings = kwargs.get("api_settings")
        if api_settings is None and args:
            api_settings = args[0]
        kwargs["transport"] = transport
        captured["kwargs"] = kwargs
        captured["api_settings"] = api_settings
        return AnkeyApiClient(
            baseUrl=f"https://{api_settings.host}:{api_settings.port}",
            username=api_settings.username,
            password=api_settings.password,
            transport=kwargs["transport"],
        )

    monkeypatch.setattr(check_api_command, "build_api_client", factory)
    result = runner.invoke(
        app,
        ["--config", str(cfg), "--host", "3.3.3.3", "--port", "3333", "--api-username", "cli_user", "--api-password", "cli_pass", "check-api"],
    )
    assert result.exit_code == 0
    api_settings = captured["api_settings"]
    assert api_settings.host == "3.3.3.3"
    assert api_settings.port == 3333
    assert api_settings.username == "cli_user"
    assert api_settings.password == "cli_pass"


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

    loaded = loadAppSettings(
        config_path=str(cfg),
        cli_overrides={
            "match_batch_size": 102,
            "match_flush_interval_ms": 202,
            "resolve_batch_size": 302,
            "resolve_flush_interval_ms": 402,
        },
    )

    assert loaded.app_settings.matching_runtime.match_batch_size == 102
    assert loaded.app_settings.matching_runtime.match_flush_interval_ms == 202
    assert loaded.app_settings.matching_runtime.resolve_batch_size == 302
    assert loaded.app_settings.matching_runtime.resolve_flush_interval_ms == 402


def test_zero_and_false_values_are_not_lost(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                "report_items_limit: 123",
                "include_deleted: true",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("ANKEY_REPORT_ITEMS_LIMIT", "0")
    monkeypatch.setenv("ANKEY_INCLUDE_DELETED", "0")

    loaded = loadAppSettings(
        config_path=str(cfg),
        cli_overrides={},
    )

    assert loaded.app_settings.observability.report_items_limit == 0
    assert loaded.app_settings.dataset.include_deleted is False


def test_field_level_source_trace(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                'host: "cfg-host"',
                "port: 1111",
                "retries: 5",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("ANKEY_PORT", "2222")

    loaded = loadAppSettings(
        config_path=str(cfg),
        cli_overrides={
            "retries": 7,
        },
    )

    assert loaded.app_settings.api.host == "cfg-host"
    assert loaded.app_settings.api.port == 2222
    assert loaded.app_settings.api.retries == 7

    assert loaded.source_trace["host"] == "config"
    assert loaded.source_trace["port"] == "env"
    assert loaded.source_trace["retries"] == "cli"
