from __future__ import annotations

from argon2 import PasswordHasher

from connector.config.models import AppConfig
from connector.delivery.cli.containers import AppContainer


def test_app_container_wires_vault_admin_password_gate_from_vault_management_settings(
    monkeypatch,
) -> None:
    password = "Container-Wired-Admin-Password"
    password_hash = PasswordHasher().hash(password)

    monkeypatch.setenv("ANKEY_GATE_HASH", password_hash)
    monkeypatch.setenv("ANKEY_GATE_PASSWORD", password)

    app_config = AppConfig.model_validate(
        {
            "vault_management": {
                "require_admin_password_for_manual_ops": True,
                "admin_password_hash_env_var": "ANKEY_GATE_HASH",
                "admin_password_env_var": "ANKEY_GATE_PASSWORD",
            }
        }
    )
    container = AppContainer()
    container.app_config.override(app_config)

    gate = container.vault_admin_password_gate()
    gate.verify_manual_access(non_interactive=True)
