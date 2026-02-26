import os

import pytest

from connector.config.loader import load_app_config
from connector.config.config import (
    SettingsLoadError,
    SettingsSourceError,
)


def _clear_ankey_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ.keys()):
        if key.startswith("ANKEY_"):
            monkeypatch.delenv(key, raising=False)


def test_source_error_for_missing_config_path(tmp_path, monkeypatch):
    _clear_ankey_env(monkeypatch)
    missing_path = tmp_path / "missing.yml"

    with pytest.raises(SettingsSourceError) as exc_info:
        load_app_config(config_path=str(missing_path), cli_overrides={})

    err = exc_info.value
    assert len(err.issues) == 1
    assert err.issues[0].code == "settings.source.config_read_failed"
    assert err.issues[0].field_path == "config_path"
    assert err.issues[0].source == "config"


def test_unknown_key_always_raises_validation_error(tmp_path, monkeypatch):
    """AppConfig has extra='forbid' — unknown keys always raise SettingsLoadError."""
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

    with pytest.raises(SettingsLoadError) as exc_info:
        load_app_config(config_path=str(cfg), cli_overrides={})

    issues = exc_info.value.issues
    assert len(issues) >= 1
    assert any(issue.code == "settings.unknown_key" for issue in issues)


def test_invalid_value_raises_settings_load_error(tmp_path, monkeypatch):
    """Pydantic validation failure → SettingsLoadError with settings.parse.invalid_value."""
    _clear_ankey_env(monkeypatch)
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                "api:",
                "  retries: not-an-int",
            ]
        ),
        encoding="utf-8",
    )

    with pytest.raises(SettingsLoadError) as exc_info:
        load_app_config(config_path=str(cfg), cli_overrides={})

    issues = exc_info.value.issues
    assert len(issues) >= 1
    assert all(issue.code == "settings.parse.invalid_value" for issue in issues)
