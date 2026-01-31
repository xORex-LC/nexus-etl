from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, ContextManager, Protocol, Sequence


class UpsertResult(str, Enum):
    """
    Назначение:
        Результат операции upsert в кэше.
    """

    INSERTED = "inserted"
    UPDATED = "updated"


@dataclass(frozen=True)
class CacheMeta:
    """
    Назначение:
        Контейнер метаданных кэша.
    """

    values: dict[str, str | None]


class CacheRepositoryProtocol(Protocol):
    """
    Назначение/ответственность:
        Порт доступа к кэшу (dataset-agnostic).
    Взаимодействия:
        Используется usecases cache-refresh/status/clear.
    """

    def transaction(self) -> ContextManager[None]: ...

    def upsert(self, dataset: str, write_model: dict) -> UpsertResult: ...
    def count(self, dataset: str) -> int: ...
    def count_by_table(self, dataset: str) -> dict[str, int]: ...
    def clear(self, dataset: str) -> None: ...
    def list_datasets(self) -> list[str]: ...

    def get_meta(self, dataset: str | None = None) -> CacheMeta: ...
    def set_meta(self, dataset: str | None, key: str, value: str | None) -> None: ...
    def reset_meta(self, dataset: str) -> None: ...

    def find(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> list[dict]: ...

    def find_one(
        self,
        dataset: str,
        filters: dict[str, Any],
        *,
        include_deleted: bool = False,
        mode: str = "exact",
    ) -> dict | None: ...
