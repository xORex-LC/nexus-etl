"""
Назначение:
    Policy-driven maintenance orchestration для vault key lifecycle.

Граница ответственности:
    - Проверяет `rotation due` через доменную `VaultRotationPolicy`.
    - Запускает rotate только при due=true.
    - Обрабатывает recovery-сценарий in-flight bridge keyring.
    - Не выполняет filesystem/storage IO напрямую.
"""

from __future__ import annotations

from uuid import uuid4

import structlog

from connector.common.time import get_utc_now_iso
from connector.domain.secrets.policy.rotation_policy import VaultRotationPolicy
from connector.usecases.management.vault.contracts import NowFactory, RunIdFactory, VaultKeyManagementProtocol
from connector.usecases.management.vault.models import VaultMaintenanceResult


class VaultMaintenanceUseCase:
    """
    Назначение:
        Выполнить maintenance цикл: recovery bridge -> due check -> rotate.

    Инварианты:
        - in-flight bridge имеет приоритет над due-check;
        - при `due=false` maintenance завершаетcя no-op без изменений;
        - run_id единый для одного запуска maintenance.
    """

    def __init__(
        self,
        *,
        key_management: VaultKeyManagementProtocol,
        rotation_policy: VaultRotationPolicy,
        now_utc: NowFactory = get_utc_now_iso,
        run_id_factory: RunIdFactory | None = None,
    ) -> None:
        self._key_management = key_management
        self._rotation_policy = rotation_policy
        self._now_utc = now_utc
        self._run_id_factory = run_id_factory or _default_maintenance_run_id
        self._logger = structlog.get_logger(__name__)

    def run_if_due(self) -> VaultMaintenanceResult:
        """Назначение:
            Выполнить maintenance цикл и вернуть структурированный результат.

        Алгоритм:
            1) Прочитать статус keyring/metadata.
            2) Если найден bridge keyring — выполнить safe-finalization и завершить.
            3) Иначе вычислить due по `VaultRotationPolicy`.
            4) При due=false вернуть no-op.
            5) При due=true выполнить rotate+rewrap.
        """
        run_id = self._run_id_factory()
        self._logger.info(
            "vault_mgmt_maintenance",
            component="vault_management",
            op="start",
            run_id=run_id,
        )

        status = self._key_management.status()
        if status.bridge_keyring:
            finalized = self._key_management.finalize_inflight_bridge(run_id=run_id)
            if finalized is None:
                self._logger.info(
                    "vault_mgmt_maintenance",
                    component="vault_management",
                    op="success",
                    run_id=run_id,
                    action="no_op",
                    reason="bridge_not_detected_on_finalize",
                )
                return VaultMaintenanceResult(
                    run_id=run_id,
                    action="no_op",
                    due=False,
                    bridge_detected=True,
                    changed=False,
                    active_key_version=status.active_key_version,
                )

            self._logger.info(
                "vault_mgmt_maintenance",
                component="vault_management",
                op="success",
                run_id=run_id,
                action="bridge_finalize",
                active_key_version=finalized.active_key_version,
                dek_rewrapped_count=finalized.dek_rewrapped_count,
            )
            return VaultMaintenanceResult(
                run_id=run_id,
                action="bridge_finalize",
                due=False,
                bridge_detected=True,
                changed=True,
                active_key_version=finalized.active_key_version,
                dek_rewrapped_count=finalized.dek_rewrapped_count,
            )

        due = self._rotation_policy.is_due(
            last_rotated_at=status.last_rotated_at,
            now_utc=self._now_utc(),
        )
        if not due:
            self._logger.info(
                "vault_mgmt_maintenance",
                component="vault_management",
                op="skipped_due",
                run_id=run_id,
                action="no_op",
                due=False,
            )
            return VaultMaintenanceResult(
                run_id=run_id,
                action="no_op",
                due=False,
                bridge_detected=False,
                changed=False,
                active_key_version=status.active_key_version,
            )

        rotated = self._key_management.rotate_and_rewrap(run_id=run_id)
        self._logger.info(
            "vault_mgmt_maintenance",
            component="vault_management",
            op="success",
            run_id=run_id,
            action="rotate",
            active_key_version=rotated.active_key_version,
            dek_rewrapped_count=rotated.dek_rewrapped_count,
        )
        return VaultMaintenanceResult(
            run_id=run_id,
            action="rotate",
            due=True,
            bridge_detected=False,
            changed=True,
            active_key_version=rotated.active_key_version,
            dek_rewrapped_count=rotated.dek_rewrapped_count,
        )


def _default_maintenance_run_id() -> str:
    return f"vault_maintenance_{uuid4().hex}"


__all__ = ["VaultMaintenanceUseCase"]

