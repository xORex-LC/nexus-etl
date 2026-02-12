from __future__ import annotations

from connector.domain.ports.cache.roles import ApplyRuntimePort, CacheAdminPort, CacheRefreshPort


class SqliteCacheRefreshAdapter(CacheRefreshPort):
    """
    Role adapter для cache-refresh пути (snapshot + post-apply sync).
    """

    def __init__(self, admin: CacheAdminPort, apply_runtime: ApplyRuntimePort) -> None:
        self._admin = admin
        self._apply_runtime = apply_runtime

    def transaction(self):
        return self._admin.transaction()

    def upsert(self, dataset: str, write_model: dict):
        return self._admin.upsert(dataset, write_model)

    def count(self, dataset: str) -> int:
        return self._admin.count(dataset)

    def count_by_table(self, dataset: str) -> dict[str, int]:
        return self._admin.count_by_table(dataset)

    def clear(self, dataset: str) -> None:
        self._admin.clear(dataset)

    def rebuild(self, dataset: str) -> None:
        self._admin.rebuild(dataset)

    def list_datasets(self) -> list[str]:
        return self._admin.list_datasets()

    def get_meta(self, dataset: str | None = None):
        return self._admin.get_meta(dataset)

    def set_meta(self, dataset: str | None, key: str, value: str | None) -> None:
        self._admin.set_meta(dataset, key, value)

    def reset_meta(self, dataset: str) -> None:
        self._admin.reset_meta(dataset)

    def upsert_identity(self, dataset: str, identity_key: str, resolved_id: str) -> None:
        self._apply_runtime.upsert_identity(dataset, identity_key, resolved_id)

    def list_pending_for_key(self, dataset: str, lookup_key: str):
        return self._apply_runtime.list_pending_for_key(dataset, lookup_key)

    def mark_resolved(self, pending_id: int) -> None:
        self._apply_runtime.mark_resolved(pending_id)
