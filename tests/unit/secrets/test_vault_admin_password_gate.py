from __future__ import annotations

from pathlib import Path

import pytest
import structlog.testing
from argon2 import PasswordHasher

from connector.common.interactive_io import InteractiveIoGate
from connector.domain.secrets.errors import (
    VaultAdminAccessDeniedError,
    VaultAdminPasswordConfigError,
)
from connector.infra.secrets.management.admin_password_gate import (
    VaultAdminPasswordGate,
)


def _hash_file(tmp_path: Path, raw_hash: str) -> Path:
    path = tmp_path / "vault-admin.env"
    path.write_text(f"ANKEY_VAULT_ADMIN_PASSWORD_HASH={raw_hash}\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def _build_gate(
    *,
    env: dict[str, str],
    hash_file: Path | None,
    require_admin_password_for_manual_ops: bool = True,
    prompt_password=None,
    interactive_io_gate=None,
) -> VaultAdminPasswordGate:
    return VaultAdminPasswordGate(
        require_admin_password_for_manual_ops=require_admin_password_for_manual_ops,
        admin_password_hash_file=str(hash_file) if hash_file is not None else None,
        admin_password_hash_name="ANKEY_VAULT_ADMIN_PASSWORD_HASH",
        admin_password_env_var="ANKEY_VAULT_ADMIN_PASSWORD",
        env=env,
        prompt_password=prompt_password,
        interactive_io_gate=interactive_io_gate,
    )


def test_verify_manual_access_skips_when_policy_disabled() -> None:
    gate = _build_gate(
        env={}, hash_file=None, require_admin_password_for_manual_ops=False
    )

    with structlog.testing.capture_logs() as cap:
        gate.verify_manual_access(non_interactive=True)

    assert cap[0]["event"] == "vault_admin_password_gate_skipped"
    assert cap[0]["reason"] == "policy_disabled"


def test_verify_manual_access_non_interactive_success(tmp_path: Path) -> None:
    password = "Admin-Secret-2026"
    gate = _build_gate(
        env={"ANKEY_VAULT_ADMIN_PASSWORD": password},
        hash_file=_hash_file(tmp_path, PasswordHasher().hash(password)),
    )

    gate.verify_manual_access(non_interactive=True)


def test_verify_manual_access_rejects_open_hash_file_permissions(
    tmp_path: Path,
) -> None:
    hash_file = _hash_file(tmp_path, PasswordHasher().hash("expected"))
    hash_file.chmod(0o644)
    gate = _build_gate(
        env={"ANKEY_VAULT_ADMIN_PASSWORD": "expected"}, hash_file=hash_file
    )

    with pytest.raises(VaultAdminPasswordConfigError) as exc_info:
        gate.verify_manual_access(non_interactive=True)

    assert (
        exc_info.value.details["reason"]
        == "admin_password_hash_file_permissions_too_open"
    )


def test_verify_manual_access_rejects_missing_hash_file_variable(
    tmp_path: Path,
) -> None:
    hash_file = tmp_path / "vault-admin.env"
    hash_file.write_text("OTHER_HASH=value\n", encoding="utf-8")
    hash_file.chmod(0o600)
    gate = _build_gate(
        env={"ANKEY_VAULT_ADMIN_PASSWORD": "expected"}, hash_file=hash_file
    )

    with pytest.raises(VaultAdminPasswordConfigError) as exc_info:
        gate.verify_manual_access(non_interactive=True)

    assert exc_info.value.details["reason"] == "admin_password_hash_missing"


def test_verify_manual_access_interactive_success(tmp_path: Path) -> None:
    password = "Interactive-Admin-Secret-2026"
    gate = _build_gate(
        env={},
        hash_file=_hash_file(tmp_path, PasswordHasher().hash(password)),
        prompt_password=lambda _: password,
    )

    gate.verify_manual_access(non_interactive=False)


def test_verify_manual_access_requires_configured_hash_file() -> None:
    gate = _build_gate(env={"ANKEY_VAULT_ADMIN_PASSWORD": "value"}, hash_file=None)

    with pytest.raises(VaultAdminPasswordConfigError) as exc_info:
        gate.verify_manual_access(non_interactive=True)

    assert exc_info.value.details["reason"] == "admin_password_hash_file_missing"


def test_verify_manual_access_raises_for_non_argon2id_hash(tmp_path: Path) -> None:
    gate = _build_gate(
        env={"ANKEY_VAULT_ADMIN_PASSWORD": "value"},
        hash_file=_hash_file(tmp_path, "$argon2i$v=19$m=65536,t=3,p=4$hash"),
    )

    with pytest.raises(VaultAdminPasswordConfigError) as exc_info:
        gate.verify_manual_access(non_interactive=True)

    assert exc_info.value.details["reason"] == "unsupported_hash_algorithm"


def test_verify_manual_access_non_interactive_requires_password_env_var(
    tmp_path: Path,
) -> None:
    gate = _build_gate(
        env={}, hash_file=_hash_file(tmp_path, PasswordHasher().hash("expected"))
    )

    with pytest.raises(VaultAdminPasswordConfigError) as exc_info:
        gate.verify_manual_access(non_interactive=True)

    assert exc_info.value.details["reason"] == "admin_password_missing"


def test_verify_manual_access_raises_for_password_mismatch_and_logs_are_safe(
    tmp_path: Path,
) -> None:
    expected_password = "Expected-Admin-Secret-2026"
    wrong_password = "Wrong-Admin-Secret-2026"
    password_hash = PasswordHasher().hash(expected_password)
    gate = _build_gate(
        env={"ANKEY_VAULT_ADMIN_PASSWORD": wrong_password},
        hash_file=_hash_file(tmp_path, password_hash),
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


def test_verify_manual_access_rejects_invalid_argon2_hash(tmp_path: Path) -> None:
    gate = _build_gate(
        env={"ANKEY_VAULT_ADMIN_PASSWORD": "any-value"},
        hash_file=_hash_file(tmp_path, "$argon2id$invalid_hash_payload"),
    )

    with pytest.raises(VaultAdminPasswordConfigError) as exc_info:
        gate.verify_manual_access(non_interactive=True)

    assert exc_info.value.details["reason"] == "invalid_password_hash"


def test_verify_manual_access_interactive_prompt_failure_maps_to_access_denied(
    tmp_path: Path,
) -> None:
    gate = _build_gate(
        env={},
        hash_file=_hash_file(tmp_path, PasswordHasher().hash("expected-password")),
        prompt_password=lambda _: (_ for _ in ()).throw(RuntimeError("tty_error")),
    )

    with pytest.raises(VaultAdminAccessDeniedError) as exc_info:
        gate.verify_manual_access(non_interactive=False)

    assert exc_info.value.details["reason"] == "password_prompt_failed"


def test_verify_manual_access_marks_prompt_window_as_interactive(
    tmp_path: Path,
) -> None:
    interactive_io_gate = InteractiveIoGate()

    def _prompt(_message: str) -> str:
        assert interactive_io_gate.is_active() is True
        return "Interactive-Admin-Secret-2026"

    gate = _build_gate(
        env={},
        hash_file=_hash_file(
            tmp_path, PasswordHasher().hash("Interactive-Admin-Secret-2026")
        ),
        prompt_password=_prompt,
        interactive_io_gate=interactive_io_gate,
    )

    gate.verify_manual_access(non_interactive=False)
