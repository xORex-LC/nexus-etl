from __future__ import annotations

from cryptography.fernet import Fernet
import pytest

from connector.domain.secrets.errors import SecretKeyConfigError
from connector.infra.secrets.env_key_provider import EnvVaultKeyProvider, parse_master_keyring


def _new_key() -> str:
    return Fernet.generate_key().decode("utf-8")


def test_parse_master_keyring_builds_active_and_fallback_keys():
    first = _new_key()
    second = _new_key()

    keys = parse_master_keyring(f"mk_2026:{first},mk_2025:{second}")

    assert len(keys) == 2
    assert keys[0].key_version == "mk_2026"
    assert keys[0].is_active is True
    assert keys[1].key_version == "mk_2025"
    assert keys[1].is_active is False


def test_env_vault_key_provider_find_key():
    first = _new_key()
    second = _new_key()
    provider = EnvVaultKeyProvider(
        env={"ANKEY_VAULT_MASTER_KEYS": f"mk_2026:{first},mk_2025:{second}"},
    )

    assert provider.get_active_key().key_version == "mk_2026"
    assert provider.find_key("mk_2025") is not None
    assert provider.find_key("missing") is None


def test_key_provider_raises_for_empty_keyring():
    with pytest.raises(SecretKeyConfigError) as exc_info:
        EnvVaultKeyProvider(env={"ANKEY_VAULT_MASTER_KEYS": "  "})

    assert exc_info.value.code == "VAULT_STARTUP_KEY_CONFIG_ERROR"
    assert exc_info.value.details["reason"] == "empty_keyring"


def test_key_provider_raises_for_duplicate_versions():
    first = _new_key()
    second = _new_key()

    with pytest.raises(SecretKeyConfigError) as exc_info:
        parse_master_keyring(f"mk:{first},mk:{second}")

    assert exc_info.value.code == "VAULT_STARTUP_KEY_CONFIG_ERROR"
    assert exc_info.value.details["reason"] == "duplicate_key_version"


def test_key_provider_raises_for_invalid_entry_format():
    with pytest.raises(SecretKeyConfigError) as exc_info:
        parse_master_keyring("bad-entry-without-colon")

    assert exc_info.value.code == "VAULT_STARTUP_KEY_CONFIG_ERROR"
    assert exc_info.value.details["reason"] == "invalid_entry_format"


def test_key_provider_raises_for_invalid_fernet_key():
    with pytest.raises(SecretKeyConfigError) as exc_info:
        parse_master_keyring("mk:invalid-key")

    assert exc_info.value.code == "VAULT_STARTUP_KEY_CONFIG_ERROR"
    assert exc_info.value.details["reason"] == "invalid_fernet_key"

