from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
import pytest

from connector.config.loader import load_app_config


def _write_config(tmp_path: Path, payload: dict[str, Any]) -> Path:
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("field_name", "expected_default", "config_value", "env_var", "env_raw_value", "env_expected", "cli_value"),
    [
        (
            "managed_env_file",
            None,
            "./config-vault.env",
            "ANKEY_VAULT_MANAGEMENT__MANAGED_ENV_FILE",
            "./env-vault.env",
            "./env-vault.env",
            "./cli-vault.env",
        ),
        (
            "require_admin_password_for_manual_ops",
            True,
            False,
            "ANKEY_VAULT_MANAGEMENT__REQUIRE_ADMIN_PASSWORD_FOR_MANUAL_OPS",
            "true",
            True,
            False,
        ),
        (
            "admin_password_hash_env_var",
            "ANKEY_VAULT_ADMIN_PASSWORD_HASH",
            "CFG_HASH_VAR",
            "ANKEY_VAULT_MANAGEMENT__ADMIN_PASSWORD_HASH_ENV_VAR",
            "ENV_HASH_VAR",
            "ENV_HASH_VAR",
            "CLI_HASH_VAR",
        ),
        (
            "admin_password_hash_file",
            None,
            "./config-vault-admin.env",
            "ANKEY_VAULT_MANAGEMENT__ADMIN_PASSWORD_HASH_FILE",
            "./env-vault-admin.env",
            "./env-vault-admin.env",
            "./cli-vault-admin.env",
        ),
        (
            "admin_password_env_var",
            "ANKEY_VAULT_ADMIN_PASSWORD",
            "CFG_PASSWORD_VAR",
            "ANKEY_VAULT_MANAGEMENT__ADMIN_PASSWORD_ENV_VAR",
            "ENV_PASSWORD_VAR",
            "ENV_PASSWORD_VAR",
            "CLI_PASSWORD_VAR",
        ),
        (
            "auto_rotate_enabled",
            False,
            True,
            "ANKEY_VAULT_MANAGEMENT__AUTO_ROTATE_ENABLED",
            "false",
            False,
            True,
        ),
        (
            "auto_rotate_on_error",
            "fail_closed",
            "fail_open",
            "ANKEY_VAULT_MANAGEMENT__AUTO_ROTATE_ON_ERROR",
            "fail_closed",
            "fail_closed",
            "fail_open",
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
    env_expected: object,
    cli_value: object,
) -> None:
    default_result = load_app_config()
    assert getattr(default_result.app_config.vault_management, field_name) == expected_default
    assert default_result.source_trace[f"vault_management.{field_name}"] == "default"

    cfg_file = _write_config(
        tmp_path,
        {"vault_management": {field_name: config_value}},
    )
    config_result = load_app_config(str(cfg_file))
    assert getattr(config_result.app_config.vault_management, field_name) == config_value
    assert config_result.source_trace[f"vault_management.{field_name}"] == "config"

    monkeypatch.setenv(env_var, env_raw_value)
    env_result = load_app_config(str(cfg_file))
    assert getattr(env_result.app_config.vault_management, field_name) == env_expected
    assert env_result.source_trace[f"vault_management.{field_name}"] == "env"

    cli_result = load_app_config(
        str(cfg_file),
        cli_overrides={f"vault_management.{field_name}": cli_value},
    )
    assert getattr(cli_result.app_config.vault_management, field_name) == cli_value
    assert cli_result.source_trace[f"vault_management.{field_name}"] == "cli"


def test_vault_management_interval_precedence_matrix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    default_result = load_app_config()
    assert default_result.app_config.vault_management.auto_rotate_interval.days == 30
    assert default_result.app_config.vault_management.auto_rotate_interval.hours == 0

    cfg_file = _write_config(
        tmp_path,
        {
            "vault_management": {
                "auto_rotate_interval": {
                    "hours": 2,
                    "days": 10,
                    "months": 0,
                    "years": 0,
                }
            }
        },
    )
    config_result = load_app_config(str(cfg_file))
    interval_cfg = config_result.app_config.vault_management.auto_rotate_interval
    assert interval_cfg.hours == 2
    assert interval_cfg.days == 10
    assert config_result.source_trace["vault_management.auto_rotate_interval.hours"] == "config"
    assert config_result.source_trace["vault_management.auto_rotate_interval.days"] == "config"

    monkeypatch.setenv("ANKEY_VAULT_MANAGEMENT__AUTO_ROTATE_INTERVAL", "hours=6,days=0,months=0,years=0")
    env_result = load_app_config(str(cfg_file))
    interval_env = env_result.app_config.vault_management.auto_rotate_interval
    assert interval_env.hours == 6
    assert interval_env.days == 0
    assert env_result.source_trace["vault_management.auto_rotate_interval"] == "env"

    cli_result = load_app_config(
        str(cfg_file),
        cli_overrides={
            "vault_management.auto_rotate_interval": {
                "hours": 1,
                "days": 1,
                "months": 0,
                "years": 0,
            }
        },
    )
    interval_cli = cli_result.app_config.vault_management.auto_rotate_interval
    assert interval_cli.hours == 1
    assert interval_cli.days == 1
    assert cli_result.source_trace["vault_management.auto_rotate_interval.hours"] == "cli"
    assert cli_result.source_trace["vault_management.auto_rotate_interval.days"] == "cli"
