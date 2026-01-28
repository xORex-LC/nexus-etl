from __future__ import annotations

from connector.datasets.cache_sync import CacheSyncAdapterProtocol
from connector.datasets.employees.load.cache_sync_adapter import EmployeesCacheSyncAdapter
from connector.datasets.organizations.load.cache_sync_adapter import OrganizationsCacheSyncAdapter
from connector.datasets.employees.load.cache_spec import employees_cache_spec
from connector.datasets.organizations.load.cache_spec import organizations_cache_spec
from connector.infra.cache.cache_spec import CacheSpec


def list_cache_sync_adapters() -> list[CacheSyncAdapterProtocol]:
    """
    Назначение:
        Вернуть список стратегий синхронизации кэша.
    Примечание:
        Порядок важен: сначала организации, затем сотрудники.
    """
    return [OrganizationsCacheSyncAdapter(), EmployeesCacheSyncAdapter()]


def list_cache_specs() -> list[CacheSpec]:
    """
    Назначение:
        Вернуть список CacheSpec для всех кэшируемых датасетов.
    Примечание:
        Порядок важен: сначала организации, затем сотрудники.
    """
    return [organizations_cache_spec, employees_cache_spec]


def get_cache_sync_adapter(dataset: str) -> CacheSyncAdapterProtocol:
    """
    Назначение:
        Вернуть стратегию синхронизации по имени датасета.
    """
    for adapter in list_cache_sync_adapters():
        if adapter.dataset == dataset:
            return adapter
    raise ValueError(f"Unsupported cache dataset: {dataset}")
