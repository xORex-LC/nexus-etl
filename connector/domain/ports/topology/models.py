"""DTO topology-портов — runtime-facing модели boundary-слоя

Содержит небольшие immutable data carriers для topology ports. Эти объекты
безопасно передавать между domain/usecase слоями без подтягивания infrastructure
или DSL-specific concerns.

Зона ответственности:
    - Представлять source canonical paths для builder/consumer ports
    - Представлять target hierarchy rows для target-side builders

Вне области ответственности:
    - Query methods или graph storage
    - Infrastructure adapters и bootstrap orchestration
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceTopologyCanonicalPath:
    """Canonical source hierarchy path для source-side builder-ов и consumer-ов"""

    canonical_segments: tuple[str, ...]


@dataclass(frozen=True)
class TargetHierarchyRow:
    """Target adjacency row, передаваемый в target topology builder"""

    node_id: str
    parent_id: str | None
    label: str
    payload_target_id: str | int | None = None
