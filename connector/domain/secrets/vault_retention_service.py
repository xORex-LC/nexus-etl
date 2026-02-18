"""
Назначение:
    Retention/maintenance сервис vault-слоя для post-apply lifecycle действий.

Граница ответственности:
    - выполняет cleanup только по operational metadata (`dataset/field/source_ref/run_id`);
    - не читает и не логирует plaintext секретов;
    - не требует внешнего scheduler (v1 maintenance hooks запускаются best-effort из runtime).
"""

from __future__ import annotations

from typing import Any, Mapping

from connector.domain.ports.secrets.locator import SecretLocatorPort
from connector.domain.ports.secrets.repository import SecretVaultRepositoryPort
from connector.domain.ports.secrets.retention import SecretApplyRetentionHookProtocol
from connector.domain.secrets.errors import SecretStoreError

LIFECYCLE_MODE_PERSISTENT = "persistent"
LIFECYCLE_MODE_EPHEMERAL = "ephemeral"
DEFAULT_LOCATOR_VERSION = "v1"


class VaultRetentionService(SecretApplyRetentionHookProtocol):
    """
    Назначение:
        Выполнить retention policy для секретов после успешного apply-op.

    Политика v1:
        - `persistent`: секреты сохраняются до явной cleanup-операции;
        - `ephemeral`: удаление выполняется только после успешного apply-op;
        - если apply-op завершился ошибкой, этот hook не вызывается (retry-safe no-delete).
    """

    def __init__(
        self,
        *,
        repository: SecretVaultRepositoryPort,
        locator: SecretLocatorPort,
        locator_version: str = DEFAULT_LOCATOR_VERSION,
    ) -> None:
        self._repository = repository
        self._locator = locator
        self._locator_version = locator_version

    def on_apply_success(
        self,
        *,
        dataset: str,
        op: str,
        source_ref: dict[str, Any] | None,
        secret_fields: list[str],
        secret_lifecycle: dict[str, Any] | None,
        run_id: str | None,
    ) -> Mapping[str, int]:
        """
        Назначение:
            Применить delete-on-success policy после успешного target-op.

        Возвращает:
            Операционные счётчики cleanup без чувствительных данных.
        """
        _ = op
        counters = {
            "deleted": 0,
            "kept": 0,
            "skipped": 0,
            "errors": 0,
        }
        if not secret_fields:
            return counters

        policy = _normalize_secret_lifecycle(secret_lifecycle)
        if policy["mode"] != LIFECYCLE_MODE_EPHEMERAL or not policy["delete_on_success"]:
            counters["kept"] += len(secret_fields)
            return counters

        match_key = _extract_match_key(source_ref)
        if match_key is None:
            counters["skipped"] += len(secret_fields)
            return counters

        normalized_source_ref = {"match_key": match_key}
        for field in secret_fields:
            try:
                locator_hash = self._locator.build_locator_hash(
                    dataset=dataset,
                    field=field,
                    source_ref=normalized_source_ref,
                    locator_version=self._locator_version,
                )
                deleted = self._repository.delete_secret(
                    dataset=dataset,
                    field=field,
                    locator_hash=locator_hash,
                    locator_version=self._locator_version,
                    run_id=run_id,
                )
                if deleted > 0:
                    counters["deleted"] += int(deleted)
                else:
                    counters["skipped"] += 1
            except (SecretStoreError, ValueError):
                counters["errors"] += 1

        return counters

    def run_maintenance(self) -> Mapping[str, int]:
        """
        Назначение:
            Запустить internal maintenance hooks (v1, без внешнего scheduler).
        """
        return {
            "cleanup_expired": self.cleanup_expired(),
            "cleanup_orphans": self.cleanup_orphans(),
            "rewrap_candidates": self.rewrap_candidates(),
        }

    def cleanup_expired(self) -> int:
        """
        Назначение:
            Entry point для TTL-based cleanup (v1 no-op, реализуется на следующем этапе).
        """
        return 0

    def cleanup_orphans(self) -> int:
        """
        Назначение:
            Entry point для orphan cleanup (v1 no-op, реализуется на следующем этапе).
        """
        return 0

    def rewrap_candidates(self) -> int:
        """
        Назначение:
            Entry point для DEK/key lifecycle maintenance (v1 no-op helper).
        """
        return 0


def _normalize_secret_lifecycle(raw: dict[str, Any] | None) -> dict[str, Any]:
    mode = LIFECYCLE_MODE_PERSISTENT
    delete_on_success = False
    ttl_seconds: int | None = None
    explicit_delete: bool | None = None

    if isinstance(raw, dict):
        raw_mode = raw.get("mode")
        if isinstance(raw_mode, str) and raw_mode in {LIFECYCLE_MODE_PERSISTENT, LIFECYCLE_MODE_EPHEMERAL}:
            mode = raw_mode
        raw_delete = raw.get("delete_on_success")
        if isinstance(raw_delete, bool):
            explicit_delete = raw_delete
        raw_ttl = raw.get("ttl_seconds")
        if isinstance(raw_ttl, int) and raw_ttl > 0:
            ttl_seconds = raw_ttl

    if explicit_delete is not None:
        delete_on_success = explicit_delete
    elif mode == LIFECYCLE_MODE_EPHEMERAL:
        delete_on_success = True

    return {
        "mode": mode,
        "delete_on_success": delete_on_success,
        "ttl_seconds": ttl_seconds,
    }


def _extract_match_key(source_ref: dict[str, Any] | None) -> str | None:
    if not isinstance(source_ref, dict):
        return None
    raw = source_ref.get("match_key")
    if not isinstance(raw, str):
        return None
    normalized = raw.strip()
    return normalized or None
