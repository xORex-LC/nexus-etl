"""Topology DSL compiler — topology spec to shared canonicalizer plan.

Topology-specific ответственность этого модуля сводится к тому, чтобы взять
topology YAML, скомпилировать вложенный shared canonicalization spec и вернуть
backward-compatible topology plan contract.
"""

from __future__ import annotations

from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.registry import OperationRegistry, register_core_ops
from connector.domain.transform_dsl.compilers.canonicalization import (
    CanonicalizationDsl,
    CompiledCanonicalizerPlan,
)
from connector.domain.transform_dsl.specs import (
    TopologySpec,
)

CompiledTopologyCanonicalizerPlan = CompiledCanonicalizerPlan


class TopologyDsl:
    """Скомпилировать `TopologySpec` в shared compiled canonicalizer plan."""

    def __init__(self, *, registry: OperationRegistry | None = None) -> None:
        resolved_registry = registry or OperationRegistry()
        register_core_ops(resolved_registry)
        self._registry = resolved_registry

    def compile(self, spec: TopologySpec) -> CompiledTopologyCanonicalizerPlan:
        try:
            return CanonicalizationDsl(registry=self._registry).compile(
                spec.topology.canonicalization
            )
        except DslLoadError as exc:
            raise DslLoadError(
                code="TOPOLOGY_DSL_COMPILE_INVALID",
                message=exc.message,
                details=exc.details,
            ) from exc
        except Exception as exc:
            raise DslLoadError(
                code="TOPOLOGY_DSL_COMPILE_INVALID",
                message=f"Failed to compile topology DSL: {exc}",
            ) from exc
