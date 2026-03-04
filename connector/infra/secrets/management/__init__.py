"""
Назначение:
    Infra-адаптеры vault-management.

Граница ответственности:
    - Отвечают за файловый IO для persisted keyring.
    - Не реализуют оркестрацию жизненного цикла, policy-правила и CLI-поведение.
"""

from connector.infra.secrets.management.managed_env_keyring_store import (
    VaultManagedEnvKeyringStore,
)

__all__ = ["VaultManagedEnvKeyringStore"]
