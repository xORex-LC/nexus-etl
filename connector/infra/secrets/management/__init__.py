"""
Назначение:
    Infra-адаптеры vault-management.

Граница ответственности:
    - Отвечают за инфраструктурные аспекты lifecycle-management:
      файловый IO keyring и password-gate доступа.
    - Не реализуют оркестрацию жизненного цикла, policy-правила и CLI-поведение.
"""

from connector.infra.secrets.management.managed_env_keyring_store import (
    VaultManagedEnvKeyringStore,
)
from connector.infra.secrets.management.admin_password_gate import VaultAdminPasswordGate

__all__ = ["VaultManagedEnvKeyringStore", "VaultAdminPasswordGate"]
