"""
Назначение:
    Модели результата/статуса lifecycle-операций vault-management.

Граница ответственности:
    - Только immutable DTO для usecase boundary.
    - Не содержит IO, криптографии и orchestration-логики.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class VaultKeyManagementStatus:
    """Снимок текущего состояния vault-management (keyring + metadata + DEK)."""

    key_versions: tuple[str, ...]
    active_key_version: str | None
    bridge_keyring: bool
    dek_total: int
    dek_rewrap_required: int
    last_rotated_at: str | None
    last_rotation_result: str | None
    last_rotation_reason: str | None
    last_rotation_run_id: str | None


@dataclass(frozen=True)
class VaultKeyManagementResult:
    """Результат lifecycle-операции vault-management."""

    operation: Literal["init", "rotate", "rewrap", "delete_key"]
    run_id: str
    active_key_version: str
    dek_rewrapped_count: int
    bridge_key_count: int
    final_key_count: int
    rotated_at: str | None = None


@dataclass(frozen=True)
class VaultMaintenanceResult:
    """Результат запуска policy-driven maintenance цикла для vault-management."""

    run_id: str
    action: Literal["no_op", "rotate", "bridge_finalize"]
    due: bool
    bridge_detected: bool
    changed: bool
    active_key_version: str | None = None
    dek_rewrapped_count: int = 0


__all__ = [
    "VaultKeyManagementStatus",
    "VaultKeyManagementResult",
    "VaultMaintenanceResult",
]
