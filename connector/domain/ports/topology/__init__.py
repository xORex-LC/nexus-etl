"""Экспорты runtime topology-портов и DTO."""

from connector.domain.ports.topology.builders import (
    SourcePathTopologyBuilderPort,
    TargetHierarchyTopologyBuilderPort,
)
from connector.domain.ports.topology.models import (
    SourceTopologyCanonicalPath,
    TargetHierarchyReadMeta,
    TargetHierarchyRow,
    TopologyLinkResolutionResult,
    TopologyMatchResult,
    TopologyFreshnessPolicy,
    TopologyRuntimeRequirements,
    TopologyTargetReadinessResult,
)
from connector.domain.ports.topology.observability import TopologyEventSink
from connector.domain.ports.topology.provider import (
    TopologyNotAvailableError,
    TopologyProviderPort,
)
from connector.domain.ports.topology.readers import TopologyTargetReadPort
from connector.domain.ports.topology.services import (
    SourceTopologyLocatorBuilderPort,
    TopologyLinkResolutionServicePort,
    TopologyMatchServicePort,
)

__all__ = [
    "SourcePathTopologyBuilderPort",
    "SourceTopologyLocatorBuilderPort",
    "SourceTopologyCanonicalPath",
    "TargetHierarchyReadMeta",
    "TargetHierarchyRow",
    "TargetHierarchyTopologyBuilderPort",
    "TopologyEventSink",
    "TopologyLinkResolutionResult",
    "TopologyLinkResolutionServicePort",
    "TopologyMatchResult",
    "TopologyMatchServicePort",
    "TopologyFreshnessPolicy",
    "TopologyNotAvailableError",
    "TopologyProviderPort",
    "TopologyRuntimeRequirements",
    "TopologyTargetReadinessResult",
    "TopologyTargetReadPort",
]
