"""Построитель source topology — сборка source-side forest из canonical path-ов

Строит topology snapshot из canonical source paths. Source-side ingest является
acyclic by construction, потому что parent relations выводятся из path prefix,
а не приходят как explicit id references.

Зона ответственности:
    - Преобразовывать canonical source paths в immutable topology nodes и indices
    - Генерировать deterministic synthetic ids для path prefix
    - Эмитить source-side diagnostics для blank, malformed и colliding paths

Вне области ответственности:
    - Source file reading, Polars projection или canonicalization
    - Target-side adjacency validation и cycle detection
"""

from __future__ import annotations

from collections.abc import Iterable

from connector.domain.dependency_tree.fingerprints import build_source_synthetic_id
from connector.domain.dependency_tree.models import TopologyNode
from connector.domain.dependency_tree.ports import NullTopologyTrace, TopologyTracePort
from connector.domain.dependency_tree.snapshot import TopologySnapshot
from connector.domain.diagnostics.catalog import (
    ErrorCatalog,
    build_error,
    build_warning,
)
from connector.domain.models import DiagnosticItem, DiagnosticStage
from connector.domain.ports.topology.models import SourceTopologyCanonicalPath


class SourcePathTopologyBuilder:
    """Собрать source topology snapshot из canonical path-объектов"""

    def __init__(
        self,
        *,
        catalog: ErrorCatalog,
        normalization_version: str,
        trace: TopologyTracePort | None = None,
    ) -> None:
        self._catalog = catalog
        self._normalization_version = normalization_version
        self._trace = trace or NullTopologyTrace()

    def build(
        self,
        paths: Iterable[SourceTopologyCanonicalPath],
    ) -> tuple[
        TopologySnapshot, tuple[DiagnosticItem, ...], tuple[DiagnosticItem, ...]
    ]:
        """Построить topology из canonical source path-ов

        Возвращает snapshot и diagnostics. Invalid source paths пропускаются,
        чтобы valid paths всё ещё могли сформировать usable snapshot.
        """

        nodes: dict[str, TopologyNode] = {}
        parent_by_id: dict[str, str | None] = {}
        children_by_id: dict[str, set[str]] = {}
        errors: list[DiagnosticItem] = []
        warnings: list[DiagnosticItem] = []
        seen_paths: dict[tuple[str, ...], int] = {}

        for index, path in enumerate(paths):
            segments = tuple(path.canonical_segments)
            if not segments or all(not segment.strip() for segment in segments):
                errors.append(
                    build_error(
                        catalog=self._catalog,
                        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
                        code="TOPOLOGY_SOURCE_PATH_EMPTY",
                        details={"path_index": index},
                    )
                )
                continue
            if any(not segment.strip() for segment in segments):
                warnings.append(
                    build_warning(
                        catalog=self._catalog,
                        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
                        code="TOPOLOGY_SOURCE_PATH_MALFORMED",
                        details={"path_index": index, "canonical_segments": segments},
                    )
                )
                continue
            if segments in seen_paths:
                warnings.append(
                    build_warning(
                        catalog=self._catalog,
                        stage=DiagnosticStage.TOPOLOGY_BOOTSTRAP,
                        code="TOPOLOGY_SOURCE_COLLISION",
                        details={
                            "canonical_segments": segments,
                            "kept_path_index": seen_paths[segments],
                            "dropped_path_index": index,
                        },
                    )
                )
                continue
            seen_paths[segments] = index
            self._ingest_path(
                segments=segments,
                nodes=nodes,
                parent_by_id=parent_by_id,
                children_by_id=children_by_id,
            )

        snapshot = _build_snapshot(nodes, parent_by_id, children_by_id)
        return snapshot, tuple(errors), tuple(warnings)

    def _ingest_path(
        self,
        *,
        segments: tuple[str, ...],
        nodes: dict[str, TopologyNode],
        parent_by_id: dict[str, str | None],
        children_by_id: dict[str, set[str]],
    ) -> None:
        parent_id: str | None = None
        for depth in range(1, len(segments) + 1):
            prefix = segments[:depth]
            node_id = build_source_synthetic_id(
                prefix,
                normalization_version=self._normalization_version,
            )
            if node_id not in nodes:
                canonical_name = prefix[-1]
                nodes[node_id] = TopologyNode(
                    node_id=node_id,
                    parent_id=parent_id,
                    display_name=canonical_name,
                    canonical_name=canonical_name,
                )
                parent_by_id[node_id] = parent_id
                children_by_id.setdefault(node_id, set())
                if parent_id is not None:
                    children_by_id.setdefault(parent_id, set()).add(node_id)
                self._trace.path_ingested(
                    canonical_segments=prefix,
                    synthetic_node_id=node_id,
                )
            parent_id = node_id


def _build_snapshot(
    nodes: dict[str, TopologyNode],
    parent_by_id: dict[str, str | None],
    children_by_id: dict[str, set[str]],
) -> TopologySnapshot:
    frozen_children = {
        node_id: tuple(sorted(children)) for node_id, children in children_by_id.items()
    }
    roots = tuple(
        sorted(
            node_id for node_id, parent_id in parent_by_id.items() if parent_id is None
        )
    )
    return TopologySnapshot(
        nodes_by_id=nodes,
        parent_by_id=parent_by_id,
        children_by_id=frozen_children,
        roots=roots,
    )
