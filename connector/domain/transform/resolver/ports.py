"""
Назначение:
    Domain-порты инфраструктурных сервисов resolve-стадии.

    IBatchIndexService   — per-run индекс resolved-id по identity-ключам,
                           нужен ResolveStage для lookup внутри батча.

    IPendingExpiryService — sweep + drain expired pending links,
                            вызывается через PipelineHooks (не из ResolveCore).

    IPendingCodec         — сериализация/десериализация pending payload,
                            инжектируется в ResolveCore вместо _serialize_pending_payload.
"""

from __future__ import annotations

from typing import Any, Protocol

from connector.domain.ports.cache.models import PendingLink, PendingRow
from connector.domain.transform.matcher.match_models import MatchedRow
from connector.domain.transform.resolver.pending_codec import PendingLoadResult


class IBatchIndexService(Protocol):
    """
    Назначение:
        Per-run хранилище batch-индекса resolved-id.

    Жизненный цикл:
        - set_index() вызывается ResolveContextStage после буферизации всех
          matched rows батча.
        - get() вызывается ResolveStage per-record при разрешении ссылок.

    Инвариант:
        get() бросает RuntimeError если set_index() не был вызван.
    """

    def set_index(self, index: dict[str, list[str]]) -> None: ...

    def get(self) -> dict[str, list[str]]: ...


class IPendingExpiryService(Protocol):
    """
    Назначение:
        Управление lifecycle expired pending links.

    Контракт:
        - sweep() — проверить и переместить просроченные ссылки в буфер;
                    вызывается из PipelineHooks.on_stage_complete.
        - drain_expired() — вернуть и очистить накопленный буфер.
    """

    def sweep(self) -> None: ...

    def drain_expired(self) -> list[PendingLink]: ...


class IPendingCodec(Protocol):
    """
    Назначение:
        Сериализация/десериализация pending payload.

    Контракт:
        - serialize() — создать JSON-строку для записи в storage.
        - deserialize() — восстановить список TransformResult из PendingRow.
    """

    def serialize(
        self,
        matched: MatchedRow,
        desired_state: dict[str, Any],
        meta: dict[str, Any] | None,
    ) -> str: ...

    def deserialize(self, pending_rows: list[PendingRow]) -> PendingLoadResult: ...


__all__ = ["IBatchIndexService", "IPendingExpiryService", "IPendingCodec"]
