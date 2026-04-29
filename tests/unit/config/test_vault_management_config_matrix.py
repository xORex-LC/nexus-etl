from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from connector.config.config import SettingsLoadError
from connector.config.loader import load_app_config


def _write_config(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("field_name", "expected_default", "config_value", "env_var", "env_raw_value", "cli_value"),
    [
        (
            "require_admin_password_for_manual_ops",
            True,
            False,
            "ANKEY_VAULT_MANAGEMENT__REQUIRE_ADMIN_PASSWORD_FOR_MANUAL_OPS",
            "true",
            False,
        ),
        (
            "admin_password_hash_file",
            None,
            "./config-vault-admin.env",
            "ANKEY_VAULT_MANAGEMENT__ADMIN_PASSWORD_HASH_FILE",
            "./env-vault-admin.env",
            "./cli-vault-admin.env",
        ),
        (
            "admin_password_env_var",
            "ANKEY_VAULT_ADMIN_PASSWORD",
            "CFG_PASSWORD_VAR",
            "ANKEY_VAULT_MANAGEMENT__ADMIN_PASSWORD_ENV_VAR",
            "ENV_PASSWORD_VAR",
            "CLI_PASSWORD_VAR",
        ),
    ],
)
def test_vault_management_scalar_precedence_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    field_name: str,
    expected_default: object,
    config_value: object,
    env_var: str,
    env_raw_value: str,
    cli_value: object,
) -> None:
    default_result = load_app_config()
    assert getattr(default_result.app_config.vault_management, field_name) == expected_default
    assert default_result.source_trace[f"vault_management.{field_name}"] == "default"

    cfg_file = _write_config(tmp_path, {"vault_management": {field_name: config_value}})
    config_result = load_app_config(str(cfg_file))
    assert getattr(config_result.app_config.vault_management, field_name) == config_value
    assert config_result.source_trace[f"vault_management.{field_name}"] == "config"

    monkeypatch.setenv(env_var, env_raw_value)
    env_result = load_app_config(str(cfg_file))
    assert getattr(env_result.app_config.vault_management, field_name) == config_value
    assert env_result.source_trace[f"vault_management.{field_name}"] == "config"

    cli_result = load_app_config(str(cfg_file), cli_overrides={f"vault_management.{field_name}": cli_value})
    assert getattr(cli_result.app_config.vault_management, field_name) == cli_value
    assert cli_result.source_trace[f"vault_management.{field_name}"] == "cli"


@pytest.mark.parametrize(
    "removed_field",
    [
        "managed_env_file",
        "admin_password_hash_env_var",
        "auto_rotate_enabled",
        "auto_rotate_interval",
        "auto_rotate_on_error",
    ],
)
def test_vault_management_rejects_removed_fields(tmp_path: Path, removed_field: str) -> None:
    cfg_file = _write_config(tmp_path, {"vault_management": {removed_field: "legacy"}})

    with pytest.raises(SettingsLoadError):
        load_app_config(str(cfg_file))
