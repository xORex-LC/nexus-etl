import httpx
from typer.testing import CliRunner
from connector.main import app
import connector.delivery.cli.containers as containers_mod
from connector.config.loader import load_app_config
from connector.infra.target.core.factory import (
    build_target_runtime_with_info as _real_build_target_runtime_with_info,
)

runner = CliRunner()

def test_priority_cli_over_env_over_config(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join([
            "api:",
            '  host: "1.1.1.1"',
            "  port: 1111",
            '  username: "cfg_user"',
            '  password: "cfg_pass"',
        ]),
        encoding="utf-8",
    )

    # ENV overrides config
    monkeypatch.setenv("ANKEY_API__HOST", "2.2.2.2")
    monkeypatch.setenv("ANKEY_API__PORT", "2222")
    monkeypatch.setenv("ANKEY_API__USERNAME", "env_user")
    monkeypatch.setenv("ANKEY_API__PASSWORD", "env_pass")

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
        return _real_build_target_runtime_with_info(
            api_settings,
            transport=kwargs["transport"],
            include_reader=kwargs.get("include_reader", True),
            runtime_mode=kwargs.get("runtime_mode"),
        )

    monkeypatch.setattr(containers_mod, "build_target_runtime_with_info", factory)
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
                "matching_runtime:",
                "  match_batch_size: 100",
                "  match_flush_interval_ms: 200",
                "resolver:",
                "  resolve_batch_size: 300",
                "  resolve_flush_interval_ms: 400",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ANKEY_MATCHING_RUNTIME__MATCH_BATCH_SIZE", "101")
    monkeypatch.setenv("ANKEY_MATCHING_RUNTIME__MATCH_FLUSH_INTERVAL_MS", "201")
    monkeypatch.setenv("ANKEY_RESOLVER__RESOLVE_BATCH_SIZE", "301")
    monkeypatch.setenv("ANKEY_RESOLVER__RESOLVE_FLUSH_INTERVAL_MS", "401")

    loaded = load_app_config(
        config_path=str(cfg),
        cli_overrides={
            "matching_runtime.match_batch_size": 102,
            "matching_runtime.match_flush_interval_ms": 202,
            "resolver.resolve_batch_size": 302,
            "resolver.resolve_flush_interval_ms": 402,
        },
    )

    assert loaded.app_config.matching_runtime.match_batch_size == 102
    assert loaded.app_config.matching_runtime.match_flush_interval_ms == 202
    assert loaded.app_config.resolver.resolve_batch_size == 302
    assert loaded.app_config.resolver.resolve_flush_interval_ms == 402


def test_zero_and_false_values_are_not_lost(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                "observability:",
                "  report_items_limit: 123",
                "dataset:",
                "  include_deleted: true",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("ANKEY_OBSERVABILITY__REPORT_ITEMS_LIMIT", "201")
    monkeypatch.setenv("ANKEY_DATASET__INCLUDE_DELETED", "false")

    loaded = load_app_config(
        config_path=str(cfg),
        cli_overrides={},
    )

    assert loaded.app_config.observability.report_items_limit == 201
    assert loaded.app_config.dataset.include_deleted is False


def test_field_level_source_trace(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                "api:",
                '  host: "cfg-host"',
                "  port: 1111",
                "  retries: 5",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("ANKEY_API__PORT", "2222")

    loaded = load_app_config(
        config_path=str(cfg),
        cli_overrides={
            "api.retries": 7,
        },
    )

    assert loaded.app_config.api.host == "cfg-host"
    assert loaded.app_config.api.port == 2222
    assert loaded.app_config.api.retries == 7

    assert loaded.source_trace["api.host"] == "config"
    assert loaded.source_trace["api.port"] == "env"
    assert loaded.source_trace["api.retries"] == "cli"


def test_vault_rollout_settings_loaded_from_env(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join([
            "dataset:",
            "  dataset_name: employees",
        ]),
        encoding="utf-8",
    )

    monkeypatch.setenv("ANKEY_VAULT_ROLLOUT__MODE", "canary")
    monkeypatch.setenv("ANKEY_VAULT_ROLLOUT__CANARY_PERCENT", "15")
    monkeypatch.setenv("ANKEY_VAULT_ROLLOUT__ROW_FAILURE_RATE_THRESHOLD_PCT", "2.5")

    loaded = load_app_config(
        config_path=str(cfg),
        cli_overrides={},
    )

    rollout = loaded.app_config.vault_rollout
    assert rollout.mode == "canary"
    assert rollout.canary_percent == 15
    assert rollout.row_failure_rate_threshold_pct == 2.5
