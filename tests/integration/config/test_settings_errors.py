import os

import pytest

from connector.config.app_settings import loadAppSettings
from connector.config.config import (
    SettingsConflictError,
    SettingsParseError,
    SettingsSourceError,
    SettingsValidationError,
)


def _clear_ankey_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ.keys()):
        if key.startswith("ANKEY_"):
            monkeypatch.delenv(key, raising=False)


def test_source_error_for_missing_config_path(tmp_path, monkeypatch):
    _clear_ankey_env(monkeypatch)
    missing_path = tmp_path / "missing.yml"

    with pytest.raises(SettingsSourceError) as exc_info:
        loadAppSettings(config_path=str(missing_path), cli_overrides={})

    err = exc_info.value
    assert len(err.issues) == 1
    assert err.issues[0].code == "settings.source.config_read_failed"
    assert err.issues[0].field_path == "config_path"
    assert err.issues[0].source == "config"


def test_parse_errors_are_aggregated_across_sources(tmp_path, monkeypatch):
    _clear_ankey_env(monkeypatch)
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                "page_size: not-int",
                "retries: also-not-int",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(SettingsParseError) as exc_info:
        loadAppSettings(
            config_path=str(cfg),
            cli_overrides={"match_batch_size": "cli-bad-int"},
        )

    issues = exc_info.value.issues
    paths = {issue.field_path for issue in issues}
    assert {"page_size", "retries", "match_batch_size"} <= paths
    assert all(issue.code == "settings.parse.invalid_value" for issue in issues)


def test_unknown_keys_warn_by_default(tmp_path, monkeypatch):
    _clear_ankey_env(monkeypatch)
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                "page_size: 100",
                "unknown_config_key: 1",
            ]
        ),
        encoding="utf-8",
    )

    loaded = loadAppSettings(
        config_path=str(cfg),
        cli_overrides={"unknown_cli_key": 2},
    )

    assert loaded.app_settings.refresh.page_size == 100
    assert len(loaded.warnings) == 2
    assert all(issue.code == "settings.unknown_key" for issue in loaded.warnings)
    assert {issue.source for issue in loaded.warnings} == {"config", "cli"}


def test_unknown_keys_error_in_strict_mode(tmp_path, monkeypatch):
    _clear_ankey_env(monkeypatch)
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                "unknown_config_key: 1",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(SettingsValidationError) as exc_info:
        loadAppSettings(
            config_path=str(cfg),
            cli_overrides={
                "diagnostics_strict": True,
                "unknown_cli_key": 2,
            },
        )

    issues = exc_info.value.issues
    assert len(issues) == 2
    assert all(issue.code == "settings.unknown_key" for issue in issues)
    assert {issue.source for issue in issues} == {"config", "cli"}


def test_conflict_error_for_half_configured_host_port(tmp_path, monkeypatch):
    _clear_ankey_env(monkeypatch)
    cfg = tmp_path / "config.yml"
    cfg.write_text("host: 127.0.0.1\n", encoding="utf-8")

    with pytest.raises(SettingsConflictError) as exc_info:
        loadAppSettings(config_path=str(cfg), cli_overrides={})

    issues = exc_info.value.issues
    assert len(issues) == 1
    assert issues[0].code == "settings.conflict.api_credentials"
    assert issues[0].field_path == "host/port"
