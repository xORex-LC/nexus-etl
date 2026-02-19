from __future__ import annotations

from connector.domain.secrets.policy.runtime_mode_policy import (
    RUNTIME_REASON_AUTO_WITH_SECRETS,
    RUNTIME_REASON_AUTO_WITHOUT_SECRETS,
    RUNTIME_REASON_INVALID_MODE,
    RUNTIME_REASON_LEGACY_FORCE_ON,
    RUNTIME_REASON_LEGACY_VAULT_FILE,
    RUNTIME_REASON_MODE_OFF,
    RUNTIME_REASON_MODE_ON,
    resolve_vault_runtime_mode,
)


def test_runtime_mode_auto_enables_vault_when_secrets_are_required() -> None:
    decision = resolve_vault_runtime_mode(mode="auto", requires_vault=True)
    assert decision.requested_vault is True
    assert decision.reason == RUNTIME_REASON_AUTO_WITH_SECRETS


def test_runtime_mode_auto_disables_vault_when_no_secrets() -> None:
    decision = resolve_vault_runtime_mode(mode="auto", requires_vault=False)
    assert decision.requested_vault is False
    assert decision.reason == RUNTIME_REASON_AUTO_WITHOUT_SECRETS


def test_runtime_mode_on_always_requests_vault() -> None:
    decision = resolve_vault_runtime_mode(mode="on", requires_vault=False)
    assert decision.requested_vault is True
    assert decision.reason == RUNTIME_REASON_MODE_ON


def test_runtime_mode_off_blocks_vault() -> None:
    decision = resolve_vault_runtime_mode(mode="off", requires_vault=True)
    assert decision.requested_vault is False
    assert decision.reason == RUNTIME_REASON_MODE_OFF


def test_runtime_mode_supports_legacy_vault_file_override() -> None:
    decision = resolve_vault_runtime_mode(
        mode=None,
        requires_vault=False,
        legacy_vault_file="legacy.csv",
    )
    assert decision.requested_vault is True
    assert decision.reason == RUNTIME_REASON_LEGACY_VAULT_FILE


def test_runtime_mode_supports_legacy_force_on_override() -> None:
    decision = resolve_vault_runtime_mode(
        mode=None,
        requires_vault=False,
        legacy_force_on=True,
    )
    assert decision.requested_vault is True
    assert decision.reason == RUNTIME_REASON_LEGACY_FORCE_ON


def test_runtime_mode_invalid_value_returns_invalid_reason() -> None:
    decision = resolve_vault_runtime_mode(mode="unknown", requires_vault=False)
    assert decision.requested_vault is False
    assert decision.reason == RUNTIME_REASON_INVALID_MODE
