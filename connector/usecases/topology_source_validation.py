"""Source topology validation use case — Stage G anchoring pre-pass.

Оркестрирует source-side validation path: читает source adjacency projection,
читает target membership ids, запускает чистый domain anchoring и возвращает
run-scoped validation state для pipeline filter-а.

Зона ответственности:
    - Связать source adjacency reader, target membership reader и anchoring core
    - Применить bootstrap-level policy для duplicate/hard_error случаев
    - Подготовить aggregate facts для report context

Вне области ответственности:
    - Polars/SQLite детали чтения
    - Row-level diagnostics с row_ref
    - Resolve pending/order semantics
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Literal

from connector.domain.dependency_tree import (
    SourceAdjacencyNode,
    SourceAnchoringResult,
    anchor_source_nodes,
)
from connector.domain.diagnostics.catalog import ErrorCatalog, build_error
from connector.domain.models import DiagnosticItem, DiagnosticStage
from connector.domain.ports.topology import (
    SourceAdjacencyReadPort,
    SourceTopologyValidationState,
    TopologyTargetMembershipReadPort,
)

SourceUnanchoredPolicy = Literal["skip", "warn", "hard_error"]


@dataclass(frozen=True)
class SourceTopologyValidationResult:
    """Итог Stage G pre-pass для bootstrap boundary."""

    anchoring: SourceAnchoringResult
    validation_state: SourceTopologyValidationState
    errors: tuple[DiagnosticItem, ...]
    warnings: tuple[DiagnosticItem, ...]
    source_node_count: int
    target_membership_count: int


class SourceTopologyValidationUseCase:
    """Выполнить source-side anchoring validation для self-referential dataset."""

    def __init__(
        self,
        *,
        source_reader: SourceAdjacencyReadPort,
        target_membership_reader: TopologyTargetMembershipReadPort,
        catalog: ErrorCatalog,
        pipeline_node_id_field: str | None = None,
    ) -> None:
        self._source_reader = source_reader
        self._target_membership_reader = target_membership_reader
        self._catalog = catalog
        self._pipeline_node_id_field = pipeline_node_id_field

    def validate(
        self,
        *,
        topology_dataset: str,
        node_id_field: str,
        on_unanchored: SourceUnanchoredPolicy,
    ) -> SourceTopologyValidationResult:
        """Построить dropped-id set для source adjacency batch."""

        nodes = tuple(self._source_reader.read_nodes())
        target_ids = self._target_membership_reader.read_target_ids(topology_dataset)
        anchoring = anchor_source_nodes(nodes, target_ids=target_ids)
        errors = list(_duplicate_node_diagnostics(self._catalog, nodes))
        warnings: list[DiagnosticItem] = []

        if on_unanchored == "hard_error":
            errors.extend(
                _unanchored_bootstrap_diagnostics(
                    catalog=self._catalog,
                    result=anchoring,
                    field=node_id_field,
                )
            )

        state = SourceTopologyValidationState(
            node_id_field=self._pipeline_node_id_field or node_id_field,
            dropped=anchoring.dropped,
            on_unanchored=on_unanchored,
        )
        return SourceTopologyValidationResult(
            anchoring=anchoring,
            validation_state=state,
            errors=tuple(errors),
            warnings=tuple(warnings),
            source_node_count=len(nodes),
            target_membership_count=len(target_ids),
        )


def _duplicate_node_diagnostics(
    catalog: ErrorCatalog,
    nodes: tuple[SourceAdjacencyNode, ...],
) -> tuple[DiagnosticItem, ...]:
    counts = Counter(node.node_id for node in nodes)
    return tuple(
        build_error(
            catalog=catalog,
            stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
            code="TOPOLOGY_DUPLICATE_NODE",
            field="node_id",
            message=f"Duplicate source topology node id: {node_id}",
            details={"node_id": node_id, "count": count},
        )
        for node_id, count in sorted(counts.items())
        if count > 1
    )


def _unanchored_bootstrap_diagnostics(
    *,
    catalog: ErrorCatalog,
    result: SourceAnchoringResult,
    field: str,
) -> tuple[DiagnosticItem, ...]:
    return tuple(
        build_error(
            catalog=catalog,
            stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
            code="TOPOLOGY_SOURCE_UNANCHORED",
            field=field,
            message=f"Source topology node '{node_id}' is not anchored",
            details={
                "node_id": node_id,
                "reason": verdict.reason,
                "broken_at_parent_id": verdict.broken_at_parent_id,
            },
        )
        for node_id, verdict in sorted(result.dropped.items())
    )
