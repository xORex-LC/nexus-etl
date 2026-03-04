"""Typed settings for vault-management operational usecases.

Boundary:
    - Owns immutable settings payload delivered from config projections.
    - Does not read ENV/CLI/YAML directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from connector.domain.secrets.policy.rotation_policy import VaultRotationInterval


@dataclass(frozen=True)
class VaultManagementSettings:
    """Resolved settings snapshot for vault-management runtime usecases."""

    managed_env_file: str | None
    require_admin_password_for_manual_ops: bool
    admin_password_hash_env_var: str
    admin_password_env_var: str
    auto_rotate_enabled: bool
    auto_rotate_on_error: Literal["fail_closed", "fail_open"]
    auto_rotate_interval: VaultRotationInterval

