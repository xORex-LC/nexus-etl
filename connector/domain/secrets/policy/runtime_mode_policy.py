"""Назначение:
    Runtime policy выбора vault-path для конкретного запуска команды.

Граница ответственности:
    Policy принимает только intent (`vault_mode`) и факт необходимости секретов.
    Она не проверяет rollout и не взаимодействует с инфраструктурой vault.
"""

from __future__ import annotations

from dataclasses import dataclass

VAULT_RUNTIME_MODE_AUTO = "auto"
VAULT_RUNTIME_MODE_ON = "on"
VAULT_RUNTIME_MODE_OFF = "off"

VALID_VAULT_RUNTIME_MODES = frozenset(
    {
        VAULT_RUNTIME_MODE_AUTO,
        VAULT_RUNTIME_MODE_ON,
        VAULT_RUNTIME_MODE_OFF,
    }
)

RUNTIME_REASON_MODE_ON = "runtime_mode_on"
RUNTIME_REASON_MODE_OFF = "runtime_mode_off"
RUNTIME_REASON_AUTO_WITH_SECRETS = "runtime_auto_secret_fields_detected"
RUNTIME_REASON_AUTO_WITHOUT_SECRETS = "runtime_auto_secret_fields_absent"
RUNTIME_REASON_LEGACY_FORCE_ON = "runtime_legacy_force_on"
RUNTIME_REASON_INVALID_MODE = "runtime_mode_invalid"


@dataclass(frozen=True)
class VaultRuntimeModeDecision:
    """Назначение:
        Решение runtime policy до применения rollout gate.

    Контракт:
        - `requested_vault` — сигнал для rollout policy (`requested_vault`).
        - `requires_vault` — факт, что dataset/plan содержит секретные поля.
        - `mode` всегда нормализован в `auto|on|off`.
    """

    mode: str
    requested_vault: bool
    requires_vault: bool
    explicit_mode: bool
    reason: str

    def to_context(self) -> dict[str, object]:
        """Назначение:
            Сериализуемый контекст для report/diagnostics.
        """
        return {
            "mode": self.mode,
            "requested_vault": self.requested_vault,
            "requires_vault": self.requires_vault,
            "explicit_mode": self.explicit_mode,
            "reason": self.reason,
        }


def resolve_vault_runtime_mode(
    *,
    mode: str | None,
    requires_vault: bool,
    legacy_force_on: bool = False,
) -> VaultRuntimeModeDecision:
    """Назначение:
        Определить, запрашивается ли vault-path на уровне runtime intent.

    Правила:
        - `mode=on`  -> vault path обязателен;
        - `mode=off` -> vault path запрещён;
        - `mode=auto` -> включать vault только если `requires_vault=True`;
        - `legacy_force_on=True` может принудительно включить vault для обратной совместимости вызова.
    """
    explicit_mode = mode is not None
    if mode is None and legacy_force_on:
        return _build_runtime_decision(
            mode=VAULT_RUNTIME_MODE_ON,
            requested_vault=True,
            requires_vault=requires_vault,
            explicit_mode=False,
            reason=RUNTIME_REASON_LEGACY_FORCE_ON,
        )

    normalized_mode, is_valid = _normalize_mode(mode)
    if not is_valid:
        return _build_runtime_decision(
            mode=normalized_mode,
            requested_vault=False,
            requires_vault=requires_vault,
            explicit_mode=explicit_mode,
            reason=RUNTIME_REASON_INVALID_MODE,
        )

    if normalized_mode == VAULT_RUNTIME_MODE_ON:
        return _build_runtime_decision(
            mode=normalized_mode,
            requested_vault=True,
            requires_vault=requires_vault,
            explicit_mode=explicit_mode,
            reason=RUNTIME_REASON_MODE_ON,
        )

    if normalized_mode == VAULT_RUNTIME_MODE_OFF:
        return _build_runtime_decision(
            mode=normalized_mode,
            requested_vault=False,
            requires_vault=requires_vault,
            explicit_mode=explicit_mode,
            reason=RUNTIME_REASON_MODE_OFF,
        )

    return _build_runtime_decision(
        mode=normalized_mode,
        requested_vault=requires_vault,
        requires_vault=requires_vault,
        explicit_mode=explicit_mode,
        reason=RUNTIME_REASON_AUTO_WITH_SECRETS if requires_vault else RUNTIME_REASON_AUTO_WITHOUT_SECRETS,
    )


def _normalize_mode(mode: str | None) -> tuple[str, bool]:
    if mode is None:
        return VAULT_RUNTIME_MODE_AUTO, True
    normalized = mode.strip().lower()
    if normalized in VALID_VAULT_RUNTIME_MODES:
        return normalized, True
    return VAULT_RUNTIME_MODE_AUTO, False


def _build_runtime_decision(
    *,
    mode: str,
    requested_vault: bool,
    requires_vault: bool,
    explicit_mode: bool,
    reason: str,
) -> VaultRuntimeModeDecision:
    return VaultRuntimeModeDecision(
        mode=mode,
        requested_vault=requested_vault,
        requires_vault=requires_vault,
        explicit_mode=explicit_mode,
        reason=reason,
    )


__all__ = [
    "RUNTIME_REASON_AUTO_WITHOUT_SECRETS",
    "RUNTIME_REASON_AUTO_WITH_SECRETS",
    "RUNTIME_REASON_INVALID_MODE",
    "RUNTIME_REASON_LEGACY_FORCE_ON",
    "RUNTIME_REASON_MODE_OFF",
    "RUNTIME_REASON_MODE_ON",
    "VALID_VAULT_RUNTIME_MODES",
    "VAULT_RUNTIME_MODE_AUTO",
    "VAULT_RUNTIME_MODE_OFF",
    "VAULT_RUNTIME_MODE_ON",
    "VaultRuntimeModeDecision",
    "resolve_vault_runtime_mode",
]
