"""Публичные экспорты dependency_tree подсистемы."""

from connector.domain.dependency_tree.fingerprints import (
    build_source_synthetic_id,
    build_structural_signature,
)
from connector.domain.dependency_tree.anchoring import (
    SourceAdjacencyNode,
    SourceAnchoringResult,
    SourceAnchoringVerdict,
    anchor_source_nodes,
)
from connector.domain.dependency_tree.comparison import (
    TopologyComparisonResult,
    TopologyMatchMode,
    compare_topology_candidates,
)
from connector.domain.dependency_tree.models import TopologyNode
from connector.domain.dependency_tree.ports import NullTopologyTrace, TopologyTracePort
from connector.domain.dependency_tree.readiness import (
    TopologyTargetReadinessEvaluator,
)
from connector.domain.dependency_tree.snapshot import (
    TopologyQueryPort,
    TopologySnapshot,
)
from connector.domain.dependency_tree.source_builder import SourcePathTopologyBuilder
from connector.domain.dependency_tree.target_builder import (
    TargetHierarchyTopologyBuilder,
)

__all__ = [
    "NullTopologyTrace",
    "SourceAdjacencyNode",
    "SourceAnchoringResult",
    "SourceAnchoringVerdict",
    "SourcePathTopologyBuilder",
    "TargetHierarchyTopologyBuilder",
    "TopologyComparisonResult",
    "TopologyMatchMode",
    "TopologyTargetReadinessEvaluator",
    "TopologyNode",
    "TopologyQueryPort",
    "TopologySnapshot",
    "TopologyTracePort",
    "anchor_source_nodes",
    "build_source_synthetic_id",
    "build_structural_signature",
    "compare_topology_candidates",
]
