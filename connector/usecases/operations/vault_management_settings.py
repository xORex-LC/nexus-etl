"""
Назначение:
    Typed-settings срез для operational usecases vault-management.

Граница ответственности:
    - Хранит immutable snapshot настроек, уже разрешённых на границе config-layer.
    - Не читает ENV/CLI/YAML напрямую.
"""

from __future__ import annotations

from dataclasses import dataclass

@dataclass(frozen=True)
class VaultManagementSettings:
    """Снимок настроек vault-management для runtime usecases."""

    require_admin_password_for_manual_ops: bool
    admin_password_hash_file: str | None
    admin_password_hash_name: str
    admin_password_env_var: str
