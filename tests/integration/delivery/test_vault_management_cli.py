from __future__ import annotations

import json
import warnings
from getpass import GetPassWarning
from pathlib import Path

from argon2 import PasswordHasher
from typer.testing import CliRunner

from connector.main import app

runner = CliRunner()


def _write_admin_hash(tmp_path: Path, *, password: str) -> Path:
    path = tmp_path / "vault-admin.env"
    path.write_text(
        f"ANKEY_VAULT_ADMIN_PASSWORD_HASH={PasswordHasher().hash(password)}\n",
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def _write_config(
    tmp_path: Path, *, admin_password: str = "Vault-Admin-Password-2026"
) -> Path:
    cfg = tmp_path / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                "paths:",
                f'  cache_dir: "{tmp_path / "cache"}"',
                f'  log_dir: "{tmp_path / "logs"}"',
                f'  report_dir: "{tmp_path / "reports"}"',
                "vault_management:",
                f'  admin_password_hash_file: "{_write_admin_hash(tmp_path, password=admin_password)}"',
            ]
        ),
        encoding="utf-8",
    )
    return cfg


def _last_json_payload(output: str) -> dict[str, object]:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            return json.loads(stripped)
    raise AssertionError(f"JSON payload was not found in output:\n{output}")


def _invoke(
    cfg: Path,
    args: list[str],
    *,
    admin_password: str = "Vault-Admin-Password-2026",
    input_text: str = "",
):
    return runner.invoke(
        app,
        ["--config", str(cfg), "vault-management", *args],
        env={"ANKEY_VAULT_ADMIN_PASSWORD": admin_password},
        input=input_text,
    )


def test_vault_management_help_lists_unseal_commands_only() -> None:
    result = runner.invoke(app, ["vault-management", "--help"])

    assert result.exit_code == 0
    assert "init" in result.stdout
    assert "status" in result.stdout
    assert "rotate" in result.stdout
    assert "rewrap" in result.stdout
    assert "delete-key" not in result.stdout
    assert "run-maintenance" not in result.stdout


def test_vault_management_init_and_status_verify(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)

    init_result = _invoke(
        cfg,
        ["init", "--non-interactive", "--force"],
        input_text="unseal-passphrase\nunseal-passphrase\n",
    )
    assert init_result.exit_code == 0, init_result.stdout
    init_payload = _last_json_payload(init_result.stdout)
    assert init_payload["operation"] == "init"

    status_result = _invoke(
        cfg,
        ["status", "--non-interactive", "--verify"],
        input_text="unseal-passphrase\n",
    )
    assert status_result.exit_code == 0, status_result.stdout
    status_payload = _last_json_payload(status_result.stdout)
    assert status_payload["operation"] == "status"
    assert status_payload["active_key_version"] == init_payload["active_key_version"]
    assert status_payload["verified"] is True


def test_vault_management_rotate_changes_unseal_passphrase(tmp_path: Path) -> None:
    cfg = _write_config(tmp_path)
    init_result = _invoke(
        cfg,
        ["init", "--non-interactive", "--force"],
        input_text="old-passphrase\nold-passphrase\n",
    )
    assert init_result.exit_code == 0, init_result.stdout
    old_key = _last_json_payload(init_result.stdout)["active_key_version"]

    rotate_result = _invoke(
        cfg,
        ["rotate", "--non-interactive", "--force"],
        input_text="old-passphrase\nnew-passphrase\nnew-passphrase\n",
    )
    assert rotate_result.exit_code == 0, rotate_result.stdout
    new_key = _last_json_payload(rotate_result.stdout)["active_key_version"]
    assert new_key != old_key

    bad_status = _invoke(
        cfg, ["status", "--non-interactive", "--verify"], input_text="old-passphrase\n"
    )
    assert bad_status.exit_code != 0

    good_status = _invoke(
        cfg, ["status", "--non-interactive", "--verify"], input_text="new-passphrase\n"
    )
    assert good_status.exit_code == 0, good_status.stdout


def test_vault_management_resolves_relative_hash_file_against_runtime_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    environment_dir = runtime_root / "environment"
    datasets_dir = runtime_root / "datasets"
    environment_dir.mkdir(parents=True, exist_ok=True)
    datasets_dir.mkdir(parents=True, exist_ok=True)
    (datasets_dir / "registry.yaml").write_text(
        "targets: {}\ndatasets: {}\n", encoding="utf-8"
    )
    _write_admin_hash(environment_dir, password="Vault-Admin-Password-2026")

    cfg = runtime_root / "config.yml"
    cfg.write_text(
        "\n".join(
            [
                "runtime:",
                f'  runtime_root: "{runtime_root}"',
                "paths:",
                f'  cache_dir: "{runtime_root / "cache"}"',
                f'  log_dir: "{runtime_root / "logs"}"',
                f'  report_dir: "{runtime_root / "reports"}"',
                "vault_management:",
                '  admin_password_hash_file: "./environment/vault-admin.env"',
            ]
        ),
        encoding="utf-8",
    )

    outside_cwd = tmp_path / "outside"
    outside_cwd.mkdir(parents=True, exist_ok=True)
    monkeypatch.chdir(outside_cwd)

    result = _invoke(
        cfg,
        ["init", "--non-interactive", "--force"],
        input_text="unseal-passphrase\nunseal-passphrase\n",
    )

    assert result.exit_code == 0, result.stdout


def test_vault_management_init_does_not_log_prompt_text_back_into_console(
    tmp_path: Path,
) -> None:
    cfg = _write_config(tmp_path)

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", GetPassWarning)
        result = runner.invoke(
            app,
            ["--config", str(cfg), "vault-management", "init"],
            input="\n".join(
                [
                    "y",
                    "Vault-Admin-Password-2026",
                    "unseal-passphrase",
                    "unseal-passphrase",
                    "",
                ]
            ),
        )

    assert result.exit_code == 0, result.output
    assert (
        result.output.count(
            "Подтвердить выполнение vault-management операции 'init'? [y/N]:"
        )
        == 1
    )
    assert (
        json.dumps(
            "Подтвердить выполнение vault-management операции 'init'? [y/N]:",
            ensure_ascii=True,
        )
        not in result.output
    )
    assert (
        json.dumps("Введите пароль доступа к vault: ", ensure_ascii=True)
        not in result.output
    )
    assert (
        json.dumps("Введите новую unseal passphrase", ensure_ascii=True)
        not in result.output
    )
