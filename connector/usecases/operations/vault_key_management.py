"""
Назначение:
    Backward-compatible re-export для legacy импортов
    `connector.usecases.operations.vault_key_management`.

Граница ответственности:
    - Не содержит реализации.
    - Делегирует публичный API в `connector.usecases.management.vault`.
"""

from connector.usecases.management.vault import (
    KeyVersionFactory,
    NowFactory,
    RunIdFactory,
    VaultKeyManagementResult,
    VaultKeyManagementStatus,
    VaultKeyManagementUseCase,
    VaultPostVerifyProtocol,
    VaultStartupGuardPostVerifier,
)

__all__ = [
    "RunIdFactory",
    "NowFactory",
    "KeyVersionFactory",
    "VaultPostVerifyProtocol",
    "VaultKeyManagementStatus",
    "VaultKeyManagementResult",
    "VaultStartupGuardPostVerifier",
    "VaultKeyManagementUseCase",
]
