"""
Назначение:
    Post-verify адаптеры для vault-management lifecycle операций.

Граница ответственности:
    - Инкапсулирует запуск `VaultStartupGuard` на переданном keyring.
    - Не реализует rotate/rewrap/delete orchestration.
"""

from __future__ import annotations

from connector.domain.ports.secrets.cipher import SecretCipherPort
from connector.domain.ports.secrets.key_provider import VaultKeyProviderPort, VaultMasterKey
from connector.domain.ports.secrets.repository import SecretVaultRepositoryPort
from connector.domain.secrets.errors import VaultManagementOperationError
from connector.domain.secrets.vault_startup_guard import VaultStartupGuard
from connector.domain.secrets.vault_startup_guard import (
    DEFAULT_CIPHER_ALGO as STARTUP_DEFAULT_CIPHER_ALGO,
)
from connector.domain.secrets.vault_startup_guard import (
    DEFAULT_PROBE_NAME as STARTUP_DEFAULT_PROBE_NAME,
)
from connector.domain.secrets.vault_startup_guard import (
    DEFAULT_PROBE_PAYLOAD as STARTUP_DEFAULT_PROBE_PAYLOAD,
)
from connector.domain.secrets.vault_startup_guard import (
    DEFAULT_WRAP_ALGO as STARTUP_DEFAULT_WRAP_ALGO,
)
from connector.usecases.management.vault.contracts import VaultPostVerifyProtocol


class VaultStartupGuardPostVerifier(VaultPostVerifyProtocol):
    """
    Назначение:
        Адаптер post-verify шага через `VaultStartupGuard`.

    Контракт:
        На каждый вызов создаёт guard с keyring, переданным usecase-ом,
        и выполняет `ensure_ready()` без участия process ENV.
    """

    def __init__(
        self,
        *,
        repository: SecretVaultRepositoryPort,
        cipher: SecretCipherPort,
        storage_probe,
        probe_name: str = STARTUP_DEFAULT_PROBE_NAME,
        probe_payload: str = STARTUP_DEFAULT_PROBE_PAYLOAD,
        cipher_algo: str = STARTUP_DEFAULT_CIPHER_ALGO,
        wrap_algo: str = STARTUP_DEFAULT_WRAP_ALGO,
        strict_readonly_policy: bool = True,
    ) -> None:
        self._repository = repository
        self._cipher = cipher
        self._storage_probe = storage_probe
        self._probe_name = probe_name
        self._probe_payload = probe_payload
        self._cipher_algo = cipher_algo
        self._wrap_algo = wrap_algo
        self._strict_readonly_policy = strict_readonly_policy

    def ensure_ready(self, keyring: tuple[VaultMasterKey, ...]) -> None:
        guard = VaultStartupGuard(
            repository=self._repository,
            cipher=self._cipher,
            key_provider=_StaticVaultKeyProvider(keyring),
            storage_probe=self._storage_probe,
            probe_name=self._probe_name,
            probe_payload=self._probe_payload,
            cipher_algo=self._cipher_algo,
            wrap_algo=self._wrap_algo,
            strict_readonly_policy=self._strict_readonly_policy,
        )
        guard.ensure_ready()


class _StaticVaultKeyProvider(VaultKeyProviderPort):
    """Назначение:
        In-memory key provider для post-verify шага на переданном keyring.
    """

    def __init__(self, keyring: tuple[VaultMasterKey, ...]) -> None:
        if not keyring:
            raise VaultManagementOperationError(
                "Vault keyring is empty for post-verify",
                details={"reason": "empty_keyring_for_verify"},
            )
        self._keyring = keyring
        self._active = keyring[0]
        self._by_version = {item.key_version: item for item in keyring}

    def get_active_key(self) -> VaultMasterKey:
        return self._active

    def get_all_keys(self) -> tuple[VaultMasterKey, ...]:
        return self._keyring

    def find_key(self, key_version: str) -> VaultMasterKey | None:
        return self._by_version.get(key_version)


__all__ = ["VaultStartupGuardPostVerifier"]

