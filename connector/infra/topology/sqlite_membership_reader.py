"""SQLite target membership reader — cache-backed anchor ids для Stage G.

Адаптер читает плоское множество target ids из cache dataset по полю,
заданному topology source spec. Это отдельный read path от target hierarchy
snapshot: Stage G работает в business-id space, а не в topology node_id space.

Зона ответственности:
    - Читать target membership ids через `TopologyCacheReadPort`
    - Отбрасывать пустые/null значения membership field

Вне области ответственности:
    - Graph validation и построение topology snapshot
    - Source projection и anchoring policy
"""

from __future__ import annotations

from connector.domain.ports.cache.models import CacheSpec
from connector.domain.ports.cache.roles import TopologyCacheReadPort
from connector.domain.ports.topology import TopologyTargetMembershipReadPort


class SqliteTopologyTargetMembershipReader(TopologyTargetMembershipReadPort):
    """Прочитать target membership ids из cache-backed dataset table."""

    def __init__(
        self,
        *,
        cache_read: TopologyCacheReadPort,
        cache_spec: CacheSpec,
        membership_field: str,
    ) -> None:
        self._cache_read = cache_read
        self._cache_spec = cache_spec
        self._membership_field = membership_field

    def read_target_ids(self, dataset: str) -> frozenset[str]:
        self._require_dataset(dataset)
        result: set[str] = set()
        for row in self._cache_read.read_all(dataset, include_deleted=True):
            value = row.get(self._membership_field)
            if value is None:
                continue
            normalized = str(value).strip()
            if normalized:
                result.add(normalized)
        return frozenset(result)

    def _require_dataset(self, dataset: str) -> None:
        if dataset != self._cache_spec.dataset:
            raise ValueError(
                "SqliteTopologyTargetMembershipReader is bound to dataset "
                f"{self._cache_spec.dataset!r}, got {dataset!r}"
            )
