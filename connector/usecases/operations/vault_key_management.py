"""
Назначение:
    Backward-compatible re-export для legacy импортов
    `connector.usecases.operations.vault_key_management`.

Граница ответственности:
    - Не содержит реализации.
    - Делегирует публичный API в `connector.usecases.management.vault`.
"""

from connector.usecases.management.vault import (
    KeyMaterialFactory,
    KeyVersionFactory,
    NowFactory,
    RunIdFactory,
    VaultKeyManagementResult,
    VaultKeyManagementStatus,
    VaultKeyManagementUseCase,
    VaultManagedKeyringStoreProtocol,
    VaultPostVerifyProtocol,
    VaultStartupGuardPostVerifier,
)

__all__ = [
    "RunIdFactory",
    "NowFactory",
    "KeyMaterialFactory",
    "KeyVersionFactory",
    "VaultManagedKeyringStoreProtocol",
    "VaultPostVerifyProtocol",
    "VaultKeyManagementStatus",
    "VaultKeyManagementResult",
    "VaultStartupGuardPostVerifier",
    "VaultKeyManagementUseCase",
]

