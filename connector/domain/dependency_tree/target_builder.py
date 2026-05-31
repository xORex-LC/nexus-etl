"""Построитель target topology — target-side валидация adjacency и сборка snapshot-а

Строит topology snapshot из explicit target hierarchy rows. В отличие от source
path ingest, target ingest обязан валидировать parent references и искать graph
cycles, потому что эти relations приходят из external data.

Зона ответственности:
    - Валидировать adjacency rows на duplicate ids, missing parents и cycles
    - Materialize-ить immutable topology nodes и graph indices для target data

Вне области ответственности:
    - Cache/database reading
    - Target readiness/freshness evaluation
"""

from __future__ import annotations

from collections.abc import Iterable
from graphlib import CycleError, TopologicalSorter

from connector.domain.dependency_tree.models import TopologyNode
from connector.domain.dependency_tree.ports import NullTopologyTrace, TopologyTracePort
from connector.domain.dependency_tree.snapshot import TopologySnapshot
from connector.domain.diagnostics.catalog import ErrorCatalog, build_error
from connector.domain.models import DiagnosticItem, DiagnosticStage
from connector.domain.ports.topology.models import TargetHierarchyRow


class TargetHierarchyTopologyBuilder:
    """Собрать target topology snapshot из explicit adjacency rows"""

    def __init__(
        self,
        *,
        catalog: ErrorCatalog,
        trace: TopologyTracePort | None = None,
    ) -> None:
        self._catalog = catalog
        self._trace = trace or NullTopologyTrace()

    def build(
        self,
        rows: Iterable[TargetHierarchyRow],
    ) -> tuple[
        TopologySnapshot, tuple[DiagnosticItem, ...], tuple[DiagnosticItem, ...]
    ]:
        """Провалидировать adjacency rows и построить target snapshot"""

        nodes: dict[str, TopologyNode] = {}
        parent_by_id: dict[str, str | None] = {}
        children_by_id: dict[str, set[str]] = {}
        errors: list[DiagnosticItem] = []

        for row in rows:
            if row.node_id in nodes:
                errors.append(
                    build_error(
                        catalog=self._catalog,
                        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
                        code="TOPOLOGY_DUPLICATE_NODE",
                        details={"node_id": row.node_id},
                    )
                )
                continue
            nodes[row.node_id] = TopologyNode(
                node_id=row.node_id,
                parent_id=row.parent_id,
                display_name=row.label,
                canonical_name=row.label,
            )
            parent_by_id[row.node_id] = row.parent_id
            children_by_id.setdefault(row.node_id, set())
            self._trace.node_ingested(
                node_id=row.node_id,
                parent_id=row.parent_id,
                canonical_name=row.label,
            )

        for node_id, parent_id in parent_by_id.items():
            if parent_id is None:
                continue
            if parent_id not in nodes:
                errors.append(
                    build_error(
                        catalog=self._catalog,
                        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
                        code="TOPOLOGY_PARENT_MISSING",
                        details={"node_id": node_id, "parent_id": parent_id},
                    )
                )
                continue
            children_by_id.setdefault(parent_id, set()).add(node_id)

        if errors:
            return TopologySnapshot.empty(), tuple(errors), ()

        if _has_cycle(parent_by_id):
            errors.append(
                build_error(
                    catalog=self._catalog,
                    stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
                    code="TOPOLOGY_CYCLE_DETECTED",
                )
            )
            self._trace.cycle_checked(nodes=len(nodes), has_cycle=True)
            return TopologySnapshot.empty(), tuple(errors), ()

        self._trace.cycle_checked(nodes=len(nodes), has_cycle=False)
        frozen_children = {
            node_id: tuple(sorted(children))
            for node_id, children in children_by_id.items()
        }
        roots = tuple(
            sorted(
                node_id
                for node_id, parent_id in parent_by_id.items()
                if parent_id is None
            )
        )
        snapshot = TopologySnapshot(
            nodes_by_id=nodes,
            parent_by_id=parent_by_id,
            children_by_id=frozen_children,
            roots=roots,
        )
        return snapshot, (), ()


def _has_cycle(parent_by_id: dict[str, str | None]) -> bool:
    graph = {node_id: set() for node_id in parent_by_id}
    for node_id, parent_id in parent_by_id.items():
        if parent_id is not None:
            graph[node_id].add(parent_id)
    try:
        tuple(TopologicalSorter(graph).static_order())
        return False
    except CycleError:
        return True
