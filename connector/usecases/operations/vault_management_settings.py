"""
Назначение:
    Typed-settings срез для operational usecases vault-management.

Граница ответственности:
    - Хранит immutable snapshot настроек, уже разрешённых на границе config-layer.
    - Не читает ENV/CLI/YAML напрямую.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from connector.domain.secrets.policy.rotation_policy import VaultRotationInterval


@dataclass(frozen=True)
class VaultManagementSettings:
    """Снимок настроек vault-management для runtime usecases."""

    managed_env_file: str | None
    require_admin_password_for_manual_ops: bool
    admin_password_hash_env_var: str
    admin_password_env_var: str
    auto_rotate_enabled: bool
    auto_rotate_on_error: Literal["fail_closed", "fail_open"]
    auto_rotate_interval: VaultRotationInterval
