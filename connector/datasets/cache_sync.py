from __future__ import annotations

from typing import Protocol, Any

from connector.domain.ports.cache_repo import CacheRepositoryProtocol


class CacheSyncAdapterProtocol(Protocol):
    """
    Назначение/ответственность:
        Стратегия синхронизации кэша для конкретного датасета.
    Взаимодействия:
        Используется CacheRefreshUseCase совместно с TargetPagedReader.
    """

    dataset: str
    list_path: str
    report_entity: str

    def get_item_key(self, raw_item: dict[str, Any]) -> str: ...
    def is_deleted(self, raw_item: dict[str, Any]) -> bool: ...
    def map_target_to_cache(self, raw_item: dict[str, Any]) -> dict[str, Any]: ...
    def upsert(self, repo: CacheRepositoryProtocol, mapped_item: dict[str, Any]) -> str: ...
