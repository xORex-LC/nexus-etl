"""
Назначение:
    MapperDsl: компиляция MappingSpec в MapperCore.
"""

from __future__ import annotations

from connector.domain.transform.dsl.engine import TransformationEngine
from connector.domain.transform.dsl.registry import OperationRegistry
from connector.domain.transform.dsl.specs import MappingSpec, SinkSpec
from connector.domain.transform.mapping.mapper_core import MapperCore


class MapperDsl:
    """
    Назначение/ответственность:
        Преобразует DSL-спеку маппинга в MapperCore.
    """

    def __init__(
        self,
        *,
        registry: OperationRegistry | None = None,
        engine: TransformationEngine | None = None,
    ) -> None:
        if engine is None:
            if registry is None:
                engine = TransformationEngine.with_core_ops()
            else:
                engine = TransformationEngine(registry)
        self.engine = engine

    def compile(self, spec: MappingSpec, *, sink_spec: SinkSpec | None = None) -> MapperCore:
        return MapperCore(spec, self.engine, sink_spec=sink_spec)
