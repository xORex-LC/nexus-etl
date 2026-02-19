"""
Назначение:
    ENV-адаптер VaultKeyProviderPort для master keyring.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from cryptography.fernet import Fernet

from connector.domain.ports.secrets.key_provider import VaultKeyProviderPort, VaultMasterKey
from connector.domain.secrets.errors import SecretKeyConfigError

DEFAULT_MASTER_KEYS_ENV = "ANKEY_VAULT_MASTER_KEYS"


def parse_master_keyring(raw_value: str | None, *, env_var: str = DEFAULT_MASTER_KEYS_ENV) -> tuple[VaultMasterKey, ...]:
    """
    Назначение:
        Распарсить keyring в формате `<version>:<fernet_key>,...`.

    Инварианты:
        - список ключей не пуст;
        - версии ключей уникальны;
        - каждый ключ валиден для Fernet;
        - первый ключ считается активным.
    """
    if raw_value is None or not raw_value.strip():
        raise SecretKeyConfigError(
            "Vault master keyring is empty",
            details={"env_var": env_var, "reason": "empty_keyring"},
        )

    entries = [part.strip() for part in raw_value.split(",") if part.strip()]
    if not entries:
        raise SecretKeyConfigError(
            "Vault master keyring is empty",
            details={"env_var": env_var, "reason": "empty_keyring"},
        )

    seen_versions: set[str] = set()
    keys: list[VaultMasterKey] = []
    for index, entry in enumerate(entries):
        if ":" not in entry:
            raise SecretKeyConfigError(
                "Vault master key entry has invalid format",
                details={"env_var": env_var, "reason": "invalid_entry_format", "entry_index": index},
            )
        key_version, key_material = entry.split(":", 1)
        key_version = key_version.strip()
        key_material = key_material.strip()

        if not key_version:
            raise SecretKeyConfigError(
                "Vault master key version is empty",
                details={"env_var": env_var, "reason": "empty_key_version", "entry_index": index},
            )
        if not key_material:
            raise SecretKeyConfigError(
                "Vault master key material is empty",
                details={"env_var": env_var, "reason": "empty_key_material", "key_version": key_version},
            )
        if key_version in seen_versions:
            raise SecretKeyConfigError(
                "Vault master key versions must be unique",
                details={"env_var": env_var, "reason": "duplicate_key_version", "key_version": key_version},
            )
        _validate_fernet_key(
            key_material,
            env_var=env_var,
            key_version=key_version,
            entry_index=index,
        )
        keys.append(
            VaultMasterKey(
                key_version=key_version,
                key_material=key_material,
                is_active=index == 0,
            )
        )
        seen_versions.add(key_version)

    return tuple(keys)


class EnvVaultKeyProvider(VaultKeyProviderPort):
    """
    Назначение:
        Поставщик master keys из ENV-конфигурации.
    """

    def __init__(
        self,
        *,
        env_var: str = DEFAULT_MASTER_KEYS_ENV,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._env_var = env_var
        source = env if env is not None else os.environ
        raw_value = source.get(env_var)
        self._keys = parse_master_keyring(raw_value, env_var=env_var)
        self._active_key = self._keys[0]
        self._keys_by_version = {item.key_version: item for item in self._keys}

    def get_active_key(self) -> VaultMasterKey:
        return self._active_key

    def get_all_keys(self) -> tuple[VaultMasterKey, ...]:
        return self._keys

    def find_key(self, key_version: str) -> VaultMasterKey | None:
        return self._keys_by_version.get(key_version)


def _validate_fernet_key(
    key_material: str,
    *,
    env_var: str,
    key_version: str,
    entry_index: int,
) -> None:
    try:
        Fernet(key_material.encode("utf-8"))
    except Exception as exc:
        raise SecretKeyConfigError(
            "Vault master key is not a valid Fernet key",
            details={
                "env_var": env_var,
                "reason": "invalid_fernet_key",
                "key_version": key_version,
                "entry_index": entry_index,
            },
        ) from exc

