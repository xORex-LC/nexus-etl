from __future__ import annotations

import json
from pathlib import Path

from argon2 import PasswordHasher
from typer.testing import CliRunner

import connector.delivery.cli.containers as containers_module
from connector.main import app


runner = CliRunner()


def _write_config(tmp_path: Path, *, managed_env_file: Path) -> Path:
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                "paths:",
                f'  cache_dir: "{tmp_path / "cache"}"',
                f'  log_dir: "{tmp_path / "logs"}"',
                f'  report_dir: "{tmp_path / "reports"}"',
                "vault_management:",
                f'  managed_env_file: "{managed_env_file}"',
                "  require_admin_password_for_manual_ops: true",
            ]
        ),
        encoding="utf-8",
    )
    return cfg


def _admin_env(*, password: str = "Vault-Admin-Password-2026") -> dict[str, str]:
    return {
        "ANKEY_VAULT_ADMIN_PASSWORD_HASH": PasswordHasher().hash(password),
        "ANKEY_VAULT_ADMIN_PASSWORD": password,
    }


def _last_json_payload(output: str) -> dict[str, object]:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)
    raise AssertionError(f"JSON payload was not found in output:\n{output}")


def test_vault_management_help_lists_subcommands() -> None:
    result = runner.invoke(app, ["vault-management", "--help"])

    assert result.exit_code == 0
    assert "init" in result.stdout
    assert "status" in result.stdout
    assert "rotate" in result.stdout
    assert "rewrap" in result.stdout
    assert "delete-key" in result.stdout
    assert "run-maintenance" in result.stdout


def test_vault_management_init_and_status_non_interactive(tmp_path: Path) -> None:
    managed_env_file = tmp_path / "managed-vault.env"
    cfg = _write_config(tmp_path, managed_env_file=managed_env_file)
    env = _admin_env()

    init_result = runner.invoke(
        app,
        [
            "--config",
            str(cfg),
            "vault-management",
            "init",
            "--non-interactive",
            "--force",
        ],
        env=env,
    )

    assert init_result.exit_code == 0
    init_payload = _last_json_payload(init_result.stdout)
    assert init_payload["operation"] == "init"
    assert init_payload["active_key_version"]
    assert managed_env_file.exists()

    status_result = runner.invoke(
        app,
        [
            "--config",
            str(cfg),
            "vault-management",
            "status",
        ],
        env=env,
    )

    assert status_result.exit_code == 0
    status_payload = _last_json_payload(status_result.stdout)
    assert status_payload["operation"] == "status"
    assert status_payload["active_key_version"] == init_payload["active_key_version"]
    assert status_payload["managed_env_file"] == str(managed_env_file)


def test_vault_management_rotate_dry_run_does_not_change_active_key(tmp_path: Path) -> None:
    managed_env_file = tmp_path / "managed-vault.env"
    cfg = _write_config(tmp_path, managed_env_file=managed_env_file)
    env = _admin_env()

    init_result = runner.invoke(
        app,
        [
            "--config",
            str(cfg),
            "vault-management",
            "init",
            "--non-interactive",
            "--force",
        ],
        env=env,
    )
    assert init_result.exit_code == 0
    before_key = _last_json_payload(init_result.stdout)["active_key_version"]

    rotate_result = runner.invoke(
        app,
        [
            "--config",
            str(cfg),
            "vault-management",
            "rotate",
            "--dry-run",
            "--non-interactive",
            "--force",
        ],
        env=env,
    )
    assert rotate_result.exit_code == 0
    rotate_payload = _last_json_payload(rotate_result.stdout)
    assert rotate_payload["operation"] == "rotate"
    assert rotate_payload["dry_run"] is True

    status_result = runner.invoke(
        app,
        [
            "--config",
            str(cfg),
            "vault-management",
            "status",
        ],
        env=env,
    )
    assert status_result.exit_code == 0
    after_key = _last_json_payload(status_result.stdout)["active_key_version"]
    assert after_key == before_key


def test_vault_management_managed_env_file_cli_override(tmp_path: Path) -> None:
    cfg_managed_env = tmp_path / "managed-from-config.env"
    cli_managed_env = tmp_path / "managed-from-cli.env"
    cfg = _write_config(tmp_path, managed_env_file=cfg_managed_env)
    env = _admin_env()

    result = runner.invoke(
        app,
        [
            "--config",
            str(cfg),
            "vault-management",
            "init",
            "--non-interactive",
            "--force",
            "--managed-env-file",
            str(cli_managed_env),
        ],
        env=env,
    )

    assert result.exit_code == 0
    payload = _last_json_payload(result.stdout)
    assert payload["operation"] == "init"
    assert cli_managed_env.exists()
    assert not cfg_managed_env.exists()


def test_vault_management_non_interactive_requires_password_env(tmp_path: Path) -> None:
    managed_env_file = tmp_path / "managed-vault.env"
    cfg = _write_config(tmp_path, managed_env_file=managed_env_file)

    result = runner.invoke(
        app,
        [
            "--config",
            str(cfg),
            "vault-management",
            "init",
            "--non-interactive",
            "--force",
        ],
        env={},
    )

    assert result.exit_code != 0
    assert "VAULT_MANAGEMENT_ADMIN_PASSWORD_CONFIG_ERROR" in (result.stdout + result.stderr)


def test_vault_management_no_verify_skips_post_verify_hook(tmp_path: Path, monkeypatch) -> None:
    managed_env_file = tmp_path / "managed-vault.env"
    cfg = _write_config(tmp_path, managed_env_file=managed_env_file)
    env = _admin_env()

    def _fail_verify(self, keyring):  # noqa: ANN001
        _ = self
        _ = keyring
        raise RuntimeError("verify_must_not_be_called")

    monkeypatch.setattr(containers_module.VaultStartupGuardPostVerifier, "ensure_ready", _fail_verify)

    result = runner.invoke(
        app,
        [
            "--config",
            str(cfg),
            "vault-management",
            "init",
            "--non-interactive",
            "--force",
            "--no-verify",
        ],
        env=env,
    )

    assert result.exit_code == 0
    payload = _last_json_payload(result.stdout)
    assert payload["operation"] == "init"
