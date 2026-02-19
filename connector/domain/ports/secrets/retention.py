"""
Назначение:
    Контракт post-apply retention hook для секретов.
"""

from __future__ import annotations

from typing import Any, Mapping, Protocol


class SecretApplyRetentionHookProtocol(Protocol):
    """
    Назначение:
        Выполнить retention действия после успешного target-op.

    Контракт:
        - вызывается только на success boundary apply item;
        - не должен поднимать исключения наружу (ошибки учитываются через counters);
        - возвращает только операционные счётчики без чувствительных данных.
    """

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
        ...

    def run_maintenance(self) -> Mapping[str, int]:
        """
        Контракт:
            Выполнить vault-internal maintenance hooks (v1: best-effort/no-scheduler).
        """
        ...

