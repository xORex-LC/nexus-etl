"""
Назначение:
    Backward-compatible re-export для legacy импортов
    `connector.usecases.operations.vault_maintenance`.
"""

from connector.usecases.management.vault import VaultMaintenanceResult, VaultMaintenanceUseCase

__all__ = ["VaultMaintenanceResult", "VaultMaintenanceUseCase"]

