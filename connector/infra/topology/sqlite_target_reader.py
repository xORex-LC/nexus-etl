"""SQLite target topology reader — cache-backed read seam для Stage C

Читает target hierarchy из cache SQLite и преобразует её в runtime-facing
topology DTO. Этот адаптер знает о таблице кэша и field mapping, но не
выполняет graph validation и не принимает readiness decisions.

Зона ответственности:
    - Читать adjacency rows из cache-backed dataset table
    - Извлекать revision/refresh metadata из cache meta
    - Нормализовать target labels через shared topology canonicalizer

Вне области ответственности:
    - Validation графа и построение snapshot-а
    - Readiness/freshness policy
    - DI/CLI wiring
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from datetime import datetime

from connector.domain.ports.cache.models import CacheSpec
from connector.domain.ports.cache.roles import TopologyCacheReadPort
from connector.domain.ports.topology import (
    TargetHierarchyReadMeta,
    TargetHierarchyRow,
    TopologyTargetReadPort,
)
from connector.domain.transform_dsl.compilers.topology import (
    CompiledTopologyCanonicalizer,
)


class SqliteTopologyTargetReader(TopologyTargetReadPort):
    """Прочитать target hierarchy и metadata через узкий cache read-порт"""

    def __init__(
        self,
        *,
        cache_read: TopologyCacheReadPort,
        cache_spec: CacheSpec,
        node_id_field: str,
        parent_id_field: str,
        target_label_field: str,
        canonicalizer: CompiledTopologyCanonicalizer,
        payload_target_id_field: str | None = None,
    ) -> None:
        self._cache_read = cache_read
        self._cache_spec = cache_spec
        self._node_id_field = node_id_field
        self._parent_id_field = parent_id_field
        self._target_label_field = target_label_field
        self._canonicalizer = canonicalizer
        self._payload_target_id_field = payload_target_id_field

    def read_hierarchy(self, dataset: str) -> Iterable[TargetHierarchyRow]:
        self._require_dataset(dataset)
        rows = self._cache_read.read_all(dataset, include_deleted=True)
        ordered = sorted(rows, key=lambda row: str(row[self._node_id_field]))
        return tuple(self._iter_rows(ordered))

    def read_snapshot_metadata(self, dataset: str) -> TargetHierarchyReadMeta:
        self._require_dataset(dataset)
        meta = self._cache_read.get_meta(dataset).values
        return TargetHierarchyReadMeta(
            cache_snapshot_revision=meta.get("cache_snapshot_revision")
            or meta.get("last_refresh_run_id"),
            refreshed_at=_parse_iso_datetime(
                meta.get("refreshed_at") or meta.get("last_refresh_at")
            ),
            row_count=self._cache_read.count(dataset),
        )

    def _iter_rows(self, rows: Iterable[Mapping[str, object]]) -> Iterator[TargetHierarchyRow]:
        for row in rows:
            raw_label = row[self._target_label_field]
            yield TargetHierarchyRow(
                node_id=str(row[self._node_id_field]),
                parent_id=_optional_str(row[self._parent_id_field]),
                label=_canonicalize_label(self._canonicalizer, raw_label),
                payload_target_id=(
                    row[self._payload_target_id_field]
                    if self._payload_target_id_field is not None
                    else None
                ),
            )

    def _require_dataset(self, dataset: str) -> None:
        if dataset != self._cache_spec.dataset:
            raise ValueError(
                "SqliteTopologyTargetReader is bound to dataset "
                f"{self._cache_spec.dataset!r}, got {dataset!r}"
            )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _canonicalize_label(
    canonicalizer: CompiledTopologyCanonicalizer,
    value: object,
) -> str:
    canonical_segments = canonicalizer.canonicalize_segments((str(value),))
    if not canonical_segments:
        return ""
    return canonical_segments[0]


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if value is None or value.strip() == "":
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
