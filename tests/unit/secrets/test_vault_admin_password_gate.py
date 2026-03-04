from __future__ import annotations

import pytest
import structlog.testing
from argon2 import PasswordHasher

from connector.domain.secrets.errors import (
    VaultAdminAccessDeniedError,
    VaultAdminPasswordConfigError,
)
from connector.infra.secrets.management.admin_password_gate import VaultAdminPasswordGate


def _build_gate(
    *,
    env: dict[str, str],
    require_admin_password_for_manual_ops: bool = True,
    prompt_password=None,
) -> VaultAdminPasswordGate:
    return VaultAdminPasswordGate(
        require_admin_password_for_manual_ops=require_admin_password_for_manual_ops,
        admin_password_hash_env_var="ANKEY_VAULT_ADMIN_PASSWORD_HASH",
        admin_password_env_var="ANKEY_VAULT_ADMIN_PASSWORD",
        env=env,
        prompt_password=prompt_password,
    )


def test_verify_manual_access_skips_when_policy_disabled() -> None:
    gate = _build_gate(env={}, require_admin_password_for_manual_ops=False)

    with structlog.testing.capture_logs() as cap:
        gate.verify_manual_access(non_interactive=True)

    assert cap[0]["event"] == "vault_admin_password_gate_skipped"
    assert cap[0]["reason"] == "policy_disabled"


def test_verify_manual_access_non_interactive_success() -> None:
    password = "Admin-Secret-2026"
    password_hash = PasswordHasher().hash(password)
    gate = _build_gate(
        env={
            "ANKEY_VAULT_ADMIN_PASSWORD_HASH": password_hash,
            "ANKEY_VAULT_ADMIN_PASSWORD": password,
        }
    )

    gate.verify_manual_access(non_interactive=True)


def test_verify_manual_access_interactive_success() -> None:
    password = "Interactive-Admin-Secret-2026"
    password_hash = PasswordHasher().hash(password)
    gate = _build_gate(
        env={"ANKEY_VAULT_ADMIN_PASSWORD_HASH": password_hash},
        prompt_password=lambda _: password,
    )

    gate.verify_manual_access(non_interactive=False)


def test_verify_manual_access_raises_for_missing_hash_env_var() -> None:
    gate = _build_gate(env={"ANKEY_VAULT_ADMIN_PASSWORD": "value"})

    with pytest.raises(VaultAdminPasswordConfigError) as exc_info:
        gate.verify_manual_access(non_interactive=True)

    assert exc_info.value.code == "VAULT_MANAGEMENT_ADMIN_PASSWORD_CONFIG_ERROR"
    assert exc_info.value.details["reason"] == "admin_password_hash_missing"


def test_verify_manual_access_raises_for_non_argon2id_hash() -> None:
    gate = _build_gate(
        env={
            "ANKEY_VAULT_ADMIN_PASSWORD_HASH": "$argon2i$v=19$m=65536,t=3,p=4$hash",
            "ANKEY_VAULT_ADMIN_PASSWORD": "value",
        }
    )

    with pytest.raises(VaultAdminPasswordConfigError) as exc_info:
        gate.verify_manual_access(non_interactive=True)

    assert exc_info.value.details["reason"] == "unsupported_hash_algorithm"
    assert exc_info.value.details["required_algorithm"] == "argon2id"


def test_verify_manual_access_non_interactive_requires_password_env_var() -> None:
    gate = _build_gate(
        env={"ANKEY_VAULT_ADMIN_PASSWORD_HASH": PasswordHasher().hash("expected")},
    )

    with pytest.raises(VaultAdminPasswordConfigError) as exc_info:
        gate.verify_manual_access(non_interactive=True)

    assert exc_info.value.details["reason"] == "admin_password_missing"
    assert exc_info.value.details["password_env_var"] == "ANKEY_VAULT_ADMIN_PASSWORD"


def test_verify_manual_access_raises_for_password_mismatch_and_logs_are_safe() -> None:
    expected_password = "Expected-Admin-Secret-2026"
    wrong_password = "Wrong-Admin-Secret-2026"
    password_hash = PasswordHasher().hash(expected_password)
    gate = _build_gate(
        env={
            "ANKEY_VAULT_ADMIN_PASSWORD_HASH": password_hash,
            "ANKEY_VAULT_ADMIN_PASSWORD": wrong_password,
        }
    )

    with structlog.testing.capture_logs() as cap:
        with pytest.raises(VaultAdminAccessDeniedError) as exc_info:
            gate.verify_manual_access(non_interactive=True)

    assert exc_info.value.details["reason"] == "password_mismatch"
    assert any(entry["event"] == "vault_admin_password_gate_failed" for entry in cap)
    for entry in cap:
        assert expected_password not in str(entry)
        assert wrong_password not in str(entry)
        assert password_hash not in str(entry)

