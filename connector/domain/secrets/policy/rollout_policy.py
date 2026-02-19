"""Назначение:
    Политика rollout для включения/отключения vault-путей в staged production rollout.

Граница ответственности:
    Модуль только принимает решение по режиму (`off/staging_dry_run/canary/full`).
    Он не открывает хранилище, не читает секреты и не формирует diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256

ROLLOUT_MODE_OFF = "off"
ROLLOUT_MODE_STAGING_DRY_RUN = "staging_dry_run"
ROLLOUT_MODE_CANARY = "canary"
ROLLOUT_MODE_FULL = "full"

VALID_VAULT_ROLLOUT_MODES = frozenset(
    {
        ROLLOUT_MODE_OFF,
        ROLLOUT_MODE_STAGING_DRY_RUN,
        ROLLOUT_MODE_CANARY,
        ROLLOUT_MODE_FULL,
    }
)

ROLLOUT_REASON_NOT_REQUESTED = "vault_not_requested"
ROLLOUT_REASON_MODE_OFF = "rollout_mode_off"
ROLLOUT_REASON_FULL = "rollout_full_enabled"
ROLLOUT_REASON_STAGING_DRY_RUN = "rollout_staging_dry_run"
ROLLOUT_REASON_CANARY_ENABLED = "rollout_canary_selected"
ROLLOUT_REASON_CANARY_DATASET_FILTERED = "rollout_canary_dataset_filtered"
ROLLOUT_REASON_CANARY_PERCENT_ZERO = "rollout_canary_percent_zero"
ROLLOUT_REASON_CANARY_BUCKET_FILTERED = "rollout_canary_bucket_filtered"


@dataclass(frozen=True)
class VaultRolloutPolicySettings:
    """Назначение:
        Конфигурация rollout-политики для runtime-команд.

    Контракт:
        - `mode` должен быть одним из `off|staging_dry_run|canary|full`.
        - `canary_percent` интерпретируется в диапазоне 0..100.
        - пустой `canary_datasets` означает "все датасеты".
    """

    mode: str = ROLLOUT_MODE_FULL
    canary_percent: int = 100
    canary_datasets: tuple[str, ...] = ()
    canary_seed: str = "vault-rollout-v1"


@dataclass(frozen=True)
class VaultRolloutDecision:
    """Назначение:
        Разрешённое rollout-решение, которое используется в wiring команд.
    """

    requested_vault: bool
    mode: str
    vault_enabled: bool
    startup_guard_required: bool
    force_dry_run: bool
    canary_bucket: int | None
    canary_selected: bool | None
    reason: str

    def to_context(self) -> dict[str, object]:
        """Назначение:
            Преобразовать решение в payload для report context.
        """
        return {
            "requested_vault": self.requested_vault,
            "mode": self.mode,
            "vault_enabled": self.vault_enabled,
            "startup_guard_required": self.startup_guard_required,
            "force_dry_run": self.force_dry_run,
            "canary_bucket": self.canary_bucket,
            "canary_selected": self.canary_selected,
            "reason": self.reason,
        }


def evaluate_vault_rollout(
    *,
    settings: VaultRolloutPolicySettings,
    requested_vault: bool,
    dataset: str | None,
    run_id: str | None,
    command_name: str,
) -> VaultRolloutDecision:
    """Назначение:
        Вычислить итоговое поведение vault runtime для конкретного запуска команды.

    Алгоритм:
        1. Быстрый выход, если vault path не запрошен опциями команды.
        2. Нормализовать rollout mode и обработать статические режимы (`off/full/staging_dry_run`).
        3. Для `canary` применить allowlist датасетов и hash bucket selection.
        4. Вернуть решение с явной причиной для observability/reporting.
    """
    mode = _normalize_mode(settings.mode)
    if not requested_vault:
        return _build_rollout_decision(
            requested_vault=False,
            mode=mode,
            reason=ROLLOUT_REASON_NOT_REQUESTED,
        )

    if mode == ROLLOUT_MODE_OFF:
        return _build_rollout_decision(
            requested_vault=True,
            mode=mode,
            canary_selected=False,
            reason=ROLLOUT_REASON_MODE_OFF,
        )

    if mode == ROLLOUT_MODE_FULL:
        return _build_rollout_decision(
            requested_vault=True,
            mode=mode,
            vault_enabled=True,
            startup_guard_required=True,
            reason=ROLLOUT_REASON_FULL,
        )

    if mode == ROLLOUT_MODE_STAGING_DRY_RUN:
        return _build_rollout_decision(
            requested_vault=True,
            mode=mode,
            vault_enabled=True,
            startup_guard_required=True,
            force_dry_run=command_name == "import-apply",
            reason=ROLLOUT_REASON_STAGING_DRY_RUN,
        )

    return _evaluate_canary_rollout(
        settings=settings,
        mode=mode,
        dataset=dataset,
        run_id=run_id,
    )


def compute_canary_bucket(*, seed: str, dataset: str | None, run_id: str | None) -> int:
    """Назначение:
        Детерминированно отобразить run context в bucket [0..99] для canary-сэмплинга.
    """
    raw = f"{seed}|{dataset or '<none>'}|{run_id or '<none>'}"
    digest = sha256(raw.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


def _normalize_mode(mode: str) -> str:
    normalized = (mode or "").strip().lower()
    if normalized in VALID_VAULT_ROLLOUT_MODES:
        return normalized
    return ROLLOUT_MODE_OFF


def _is_dataset_allowed(dataset: str | None, allowlist: tuple[str, ...]) -> bool:
    if not allowlist:
        return True
    if "*" in allowlist:
        return True
    if not dataset:
        return False
    return dataset in allowlist


def _evaluate_canary_rollout(
    *,
    settings: VaultRolloutPolicySettings,
    mode: str,
    dataset: str | None,
    run_id: str | None,
) -> VaultRolloutDecision:
    if not _is_dataset_allowed(dataset, settings.canary_datasets):
        return _build_rollout_decision(
            requested_vault=True,
            mode=mode,
            canary_selected=False,
            reason=ROLLOUT_REASON_CANARY_DATASET_FILTERED,
        )

    if settings.canary_percent <= 0:
        return _build_rollout_decision(
            requested_vault=True,
            mode=mode,
            canary_bucket=0,
            canary_selected=False,
            reason=ROLLOUT_REASON_CANARY_PERCENT_ZERO,
        )

    bucket = compute_canary_bucket(
        seed=settings.canary_seed,
        dataset=dataset,
        run_id=run_id,
    )
    selected = bucket < settings.canary_percent
    return _build_rollout_decision(
        requested_vault=True,
        mode=mode,
        vault_enabled=selected,
        startup_guard_required=selected,
        canary_bucket=bucket,
        canary_selected=selected,
        reason=ROLLOUT_REASON_CANARY_ENABLED if selected else ROLLOUT_REASON_CANARY_BUCKET_FILTERED,
    )


def _build_rollout_decision(
    *,
    requested_vault: bool,
    mode: str,
    reason: str,
    vault_enabled: bool = False,
    startup_guard_required: bool = False,
    force_dry_run: bool = False,
    canary_bucket: int | None = None,
    canary_selected: bool | None = None,
) -> VaultRolloutDecision:
    return VaultRolloutDecision(
        requested_vault=requested_vault,
        mode=mode,
        vault_enabled=vault_enabled,
        startup_guard_required=startup_guard_required,
        force_dry_run=force_dry_run,
        canary_bucket=canary_bucket,
        canary_selected=canary_selected,
        reason=reason,
    )


__all__ = [
    "ROLLOUT_MODE_CANARY",
    "ROLLOUT_MODE_FULL",
    "ROLLOUT_MODE_OFF",
    "ROLLOUT_MODE_STAGING_DRY_RUN",
    "ROLLOUT_REASON_CANARY_BUCKET_FILTERED",
    "ROLLOUT_REASON_CANARY_DATASET_FILTERED",
    "ROLLOUT_REASON_CANARY_ENABLED",
    "ROLLOUT_REASON_CANARY_PERCENT_ZERO",
    "ROLLOUT_REASON_FULL",
    "ROLLOUT_REASON_MODE_OFF",
    "ROLLOUT_REASON_NOT_REQUESTED",
    "ROLLOUT_REASON_STAGING_DRY_RUN",
    "VALID_VAULT_ROLLOUT_MODES",
    "VaultRolloutDecision",
    "VaultRolloutPolicySettings",
    "compute_canary_bucket",
    "evaluate_vault_rollout",
]
