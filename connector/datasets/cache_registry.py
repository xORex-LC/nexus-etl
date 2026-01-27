from __future__ import annotations

from connector.datasets.cache_sync import CacheSyncAdapterProtocol
from connector.datasets.employees.cache_sync_adapter import EmployeesCacheSyncAdapter
from connector.datasets.organizations.cache_sync_adapter import OrganizationsCacheSyncAdapter


def list_cache_sync_adapters() -> list[CacheSyncAdapterProtocol]:
    """
    Назначение:
        Вернуть список стратегий синхронизации кэша.
    Примечание:
        Порядок важен: сначала организации, затем сотрудники.
    """
    return [OrganizationsCacheSyncAdapter(), EmployeesCacheSyncAdapter()]


def get_cache_sync_adapter(dataset: str) -> CacheSyncAdapterProtocol:
    """
    Назначение:
        Вернуть стратегию синхронизации по имени датасета.
    """
    for adapter in list_cache_sync_adapters():
        if adapter.dataset == dataset:
            return adapter
    raise ValueError(f"Unsupported cache dataset: {dataset}")
