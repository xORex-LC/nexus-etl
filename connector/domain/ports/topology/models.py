"""DTO topology-портов — runtime-facing модели boundary-слоя

Содержит небольшие immutable data carriers для topology ports. Эти объекты
безопасно передавать между domain/usecase слоями без подтягивания infrastructure
или DSL-specific concerns.

Зона ответственности:
    - Представлять source canonical paths для builder/consumer ports
    - Представлять target hierarchy rows для target-side builders
    - Представлять readiness/freshness facts для target-side bootstrap path

Вне области ответственности:
    - Query methods или graph storage
    - Infrastructure adapters и bootstrap orchestration
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Mapping

from connector.domain.dependency_tree.comparison import TopologyMatchMode
from connector.domain.models import DiagnosticItem


@dataclass(frozen=True)
class SourceTopologyCanonicalPath:
    """Canonical source hierarchy path для source-side builder-ов и consumer-ов"""

    canonical_segments: tuple[str, ...]


@dataclass(frozen=True)
class TopologyMatchResult:
    """Типизированный результат topology-refinement для match-стадии."""

    matched_target_id: str | None
    is_ambiguous: bool
    mode: TopologyMatchMode
    reason: str | None
    evidence: Mapping[str, Any]


@dataclass(frozen=True)
class TargetHierarchyRow:
    """Target adjacency row, передаваемый в target topology builder

    Контракт:
        - `node_id` и `parent_id` уже приведены к stable string identifiers.
        - `label` содержит canonicalized target label, готовый для builder-а.
        - `payload_target_id` остаётся write-facing identifier и не подменяет `node_id`.
    """

    node_id: str
    parent_id: str | None
    label: str
    payload_target_id: str | int | None = None


@dataclass(frozen=True)
class TargetHierarchyReadMeta:
    """Метаданные cache-backed target hierarchy для readiness evaluation"""

    cache_snapshot_revision: str | None
    refreshed_at: datetime | None
    row_count: int


@dataclass(frozen=True)
class TopologyFreshnessPolicy:
    """Политика freshness-проверки для target topology readiness

    Инварианты:
        - `mode=max_age` требует положительный `max_age_seconds`.
        - `require_revision=True` усиливает policy независимо от базового режима.
    """

    mode: Literal["none", "max_age", "revision_required"] = "none"
    max_age_seconds: int | None = None
    require_revision: bool = False

    def __post_init__(self) -> None:
        if self.max_age_seconds is not None and self.max_age_seconds <= 0:
            raise ValueError("TopologyFreshnessPolicy.max_age_seconds must be > 0")
        if self.mode == "max_age" and self.max_age_seconds is None:
            raise ValueError(
                "TopologyFreshnessPolicy.max_age_seconds is required for mode='max_age'"
            )


@dataclass(frozen=True)
class TopologyTargetReadinessResult:
    """Результат readiness-оценки target topology перед runtime bootstrap"""

    is_ready: bool
    errors: tuple[DiagnosticItem, ...]
    warnings: tuple[DiagnosticItem, ...]
    details: Mapping[str, Any]


@dataclass(frozen=True)
class TopologyRuntimeRequirements:
    """Run-scoped семантика topology activation для pipeline composition.

    Этот DTO не хранит snapshot-ы и не подменяет provider boundary. Он нужен как
    composition input для topology-aware consumer-ов, которым важно понимать,
    была ли topology затребована, для какого dataset и по какой activation reason.
    """

    pipeline_dataset: str
    topology_dataset: str
    requires_source_topology: bool
    requires_target_topology: bool
    activation_sources: tuple[str, ...]
    skipped_reason: str | None = None
