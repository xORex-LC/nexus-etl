"""Назначение:
    Пакет чистых policy-модулей vault-слоя.

Граница ответственности:
    Модули пакета не выполняют IO, не открывают хранилища и не зависят от delivery/infra.
    Они принимают входные сигналы runtime и возвращают детерминированные решения.
"""

from connector.domain.secrets.policy.retention_policy import (
    DEFAULT_LOCATOR_VERSION,
    LIFECYCLE_MODE_EPHEMERAL,
    LIFECYCLE_MODE_PERSISTENT,
    normalize_secret_lifecycle,
)
from connector.domain.secrets.policy.rollout_metrics import (
    VaultRolloutThresholds,
    build_vault_operational_metrics,
)
from connector.domain.secrets.policy.rollout_policy import (
    ROLLOUT_MODE_CANARY,
    ROLLOUT_MODE_FULL,
    ROLLOUT_MODE_OFF,
    ROLLOUT_MODE_STAGING_DRY_RUN,
    VALID_VAULT_ROLLOUT_MODES,
    VaultRolloutDecision,
    VaultRolloutPolicySettings,
    compute_canary_bucket,
    evaluate_vault_rollout,
)
from connector.domain.secrets.policy.runtime_mode_policy import (
    VAULT_RUNTIME_MODE_AUTO,
    VAULT_RUNTIME_MODE_OFF,
    VAULT_RUNTIME_MODE_ON,
    VALID_VAULT_RUNTIME_MODES,
    RUNTIME_REASON_LEGACY_FORCE_ON,
    VaultRuntimeModeDecision,
    resolve_vault_runtime_mode,
)

__all__ = [
    "DEFAULT_LOCATOR_VERSION",
    "LIFECYCLE_MODE_EPHEMERAL",
    "LIFECYCLE_MODE_PERSISTENT",
    "ROLLOUT_MODE_CANARY",
    "ROLLOUT_MODE_FULL",
    "ROLLOUT_MODE_OFF",
    "ROLLOUT_MODE_STAGING_DRY_RUN",
    "VALID_VAULT_ROLLOUT_MODES",
    "VALID_VAULT_RUNTIME_MODES",
    "VAULT_RUNTIME_MODE_AUTO",
    "VAULT_RUNTIME_MODE_OFF",
    "VAULT_RUNTIME_MODE_ON",
    "RUNTIME_REASON_LEGACY_FORCE_ON",
    "VaultRolloutDecision",
    "VaultRolloutPolicySettings",
    "VaultRolloutThresholds",
    "VaultRuntimeModeDecision",
    "build_vault_operational_metrics",
    "compute_canary_bucket",
    "evaluate_vault_rollout",
    "normalize_secret_lifecycle",
    "resolve_vault_runtime_mode",
]
