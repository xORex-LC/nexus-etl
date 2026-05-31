"""Порты topology-reader-ов — read seam для cache-backed target hierarchy

Определяет узкий read-only контракт, через который topology use case получает
adjacency rows и freshness metadata. Чтение вынесено отдельно, чтобы readiness
evaluator не смешивал policy с data access.

Зона ответственности:
    - Определять read seam для target-side hierarchy и её provenance metadata

Вне области ответственности:
    - SQLite/cache реализация
    - Topology build validation и readiness policy evaluation
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from connector.domain.ports.topology.models import (
    TargetHierarchyReadMeta,
    TargetHierarchyRow,
)


class TopologyTargetReadPort(Protocol):
    """Прочитать cache-backed target hierarchy и связанные freshness facts"""

    def read_hierarchy(self, dataset: str) -> Iterable[TargetHierarchyRow]: ...
    def read_snapshot_metadata(self, dataset: str) -> TargetHierarchyReadMeta: ...
