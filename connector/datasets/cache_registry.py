from __future__ import annotations

from connector.datasets.cache_sync import CacheSyncAdapterProtocol
from connector.datasets.employees.cache_sync_adapter import EmployeesCacheSyncAdapter
from connector.datasets.organizations.cache_sync_adapter import OrganizationsCacheSyncAdapter


def get_cache_adapters() -> list[CacheSyncAdapterProtocol]:
    """
    Назначение:
        Вернуть список стратегий синхронизации кэша.
    Примечание:
        Порядок важен: сначала организации, затем сотрудники.
    """
    return [OrganizationsCacheSyncAdapter(), EmployeesCacheSyncAdapter()]
