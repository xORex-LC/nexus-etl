from __future__ import annotations

import json
from pathlib import Path

from argon2 import PasswordHasher
from cryptography.fernet import Fernet
from typer.testing import CliRunner

import connector.delivery.cli.containers as containers_module
from connector.config.loader import load_app_config
from connector.config.projections import to_vault_db_config
from connector.infra.secrets.sqlite.repository import SqliteVaultRepository
from connector.infra.sqlite.engine import open_sqlite
from connector.main import app


runner = CliRunner()


def _write_config(
    tmp_path: Path,
    *,
    managed_env_file: Path,
    vault_management_overrides: dict[str, object] | None = None,
) -> Path:
    vm = {
        "managed_env_file": str(managed_env_file),
        "require_admin_password_for_manual_ops": True,
    }
    if vault_management_overrides:
        vm.update(vault_management_overrides)
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                "paths:",
                f'  cache_dir: "{tmp_path / "cache"}"',
                f'  log_dir: "{tmp_path / "logs"}"',
                f'  report_dir: "{tmp_path / "reports"}"',
                "vault_management:",
                *(f"  {key}: {json.dumps(value)}" for key, value in vm.items()),
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


def _invoke_vault(cfg: Path, command_args: list[str], *, env: dict[str, str]) -> object:
    return runner.invoke(
        app,
        ["--config", str(cfg), "vault-management", *command_args],
        env=env,
    )


def _read_status(cfg: Path, *, env: dict[str, str]) -> dict[str, object]:
    result = _invoke_vault(cfg, ["status", "--non-interactive"], env=env)
    assert result.exit_code == 0, result.stdout + "\n" + result.stderr
    return _last_json_payload(result.stdout)


def _update_last_rotated_at(cfg: Path, *, iso_utc: str) -> None:
    loaded = load_app_config(str(cfg)).app_config
    vault_db_path = loaded.sqlite.vault_db_path or str(Path(loaded.paths.cache_dir) / "ankey_vault.sqlite3")
    engine = open_sqlite(to_vault_db_config(loaded), vault_db_path)
    try:
        repo = SqliteVaultRepository(engine)
        repo.set_last_rotated_at(iso_utc)
    finally:
        engine.close()


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
            "--non-interactive",
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
            "--non-interactive",
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


def test_vault_management_non_interactive_requires_force(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, managed_env_file=tmp_path / "managed-vault.env")
    env = _admin_env()

    result = _invoke_vault(
        cfg,
        ["init", "--non-interactive"],
        env=env,
    )

    assert result.exit_code != 0
    assert "--non-interactive требует --force" in (result.stdout + result.stderr)


def test_vault_management_full_lifecycle_manual_commands(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, managed_env_file=tmp_path / "managed-vault.env")
    env = _admin_env()

    init_result = _invoke_vault(cfg, ["init", "--non-interactive", "--force"], env=env)
    assert init_result.exit_code == 0
    init_key = _last_json_payload(init_result.stdout)["active_key_version"]

    rotate_result = _invoke_vault(cfg, ["rotate", "--non-interactive", "--force"], env=env)
    assert rotate_result.exit_code == 0
    rotate_payload = _last_json_payload(rotate_result.stdout)
    assert rotate_payload["operation"] == "rotate"
    rotate_key = rotate_payload["active_key_version"]
    assert rotate_key != init_key

    rewrap_result = _invoke_vault(cfg, ["rewrap", "--non-interactive", "--force"], env=env)
    assert rewrap_result.exit_code == 0
    rewrap_payload = _last_json_payload(rewrap_result.stdout)
    assert rewrap_payload["operation"] == "rewrap"
    assert rewrap_payload["active_key_version"] == rotate_key

    delete_result = _invoke_vault(cfg, ["delete-key", "--non-interactive", "--force"], env=env)
    assert delete_result.exit_code == 0
    delete_payload = _last_json_payload(delete_result.stdout)
    assert delete_payload["operation"] == "delete_key"
    assert delete_payload["active_key_version"] != rotate_key

    _update_last_rotated_at(cfg, iso_utc="2020-01-01T00:00:00+00:00")
    maintenance_result = _invoke_vault(cfg, ["run-maintenance", "--non-interactive", "--force"], env=env)
    assert maintenance_result.exit_code == 0
    maintenance_payload = _last_json_payload(maintenance_result.stdout)
    assert maintenance_payload["action"] == "rotate"
    assert maintenance_payload["changed"] is True

    status_payload = _read_status(cfg, env=env)
    assert status_payload["bridge_keyring"] is False
    assert status_payload["dek_rewrap_required"] == 0


def test_vault_management_import_existing_env_flow(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path, managed_env_file=tmp_path / "managed-vault.env")
    imported_key_version = "mk_imported_env"
    imported_key_material = Fernet.generate_key().decode("utf-8")
    imported_keyring = f"{imported_key_version}:{imported_key_material}"
    env = {
        **_admin_env(),
        "ANKEY_VAULT_MASTER_KEYS": imported_keyring,
    }

    result = _invoke_vault(
        cfg,
        ["init", "--import-existing-env", "--non-interactive", "--force", "--no-verify"],
        env=env,
    )

    assert result.exit_code == 0
    payload = _last_json_payload(result.stdout)
    assert payload["operation"] == "init"
    assert payload["active_key_version"] == imported_key_version

    status_payload = _read_status(cfg, env=env)
    assert status_payload["active_key_version"] == imported_key_version


def test_vault_management_gate_uses_custom_env_var_names_from_config(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        managed_env_file=tmp_path / "managed-vault.env",
        vault_management_overrides={
            "admin_password_hash_env_var": "MY_CUSTOM_GATE_HASH",
            "admin_password_env_var": "MY_CUSTOM_GATE_PASSWORD",
        },
    )
    password = "Custom-Password-For-Vault"
    env = {
        "MY_CUSTOM_GATE_HASH": PasswordHasher().hash(password),
        "MY_CUSTOM_GATE_PASSWORD": password,
    }

    result = _invoke_vault(
        cfg,
        ["init", "--non-interactive", "--force"],
        env=env,
    )

    assert result.exit_code == 0
    payload = _last_json_payload(result.stdout)
    assert payload["operation"] == "init"


def test_vault_management_gate_can_be_disabled_by_config_policy(tmp_path: Path) -> None:
    cfg = _write_config(
        tmp_path,
        managed_env_file=tmp_path / "managed-vault.env",
        vault_management_overrides={"require_admin_password_for_manual_ops": False},
    )

    result = _invoke_vault(
        cfg,
        ["init", "--non-interactive", "--force"],
        env={},
    )

    assert result.exit_code == 0
    payload = _last_json_payload(result.stdout)
    assert payload["operation"] == "init"
