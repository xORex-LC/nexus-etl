from __future__ import annotations

from cryptography.fernet import Fernet

from connector.domain.ports.secrets.key_provider import VaultMasterKey


class StaticVaultKeyProvider:
    def __init__(self, *, key_version: str = "mk_2026", key_material: str | None = None) -> None:
        self.key = VaultMasterKey(
            key_version=key_version,
            key_material=key_material or Fernet.generate_key().decode("utf-8"),
            is_active=True,
        )

    def get_active_key(self) -> VaultMasterKey:
        return self.key

    def get_all_keys(self) -> tuple[VaultMasterKey, ...]:
        return (self.key,)

    def find_key(self, key_version: str) -> VaultMasterKey | None:
        return self.key if self.key.key_version == key_version else None
