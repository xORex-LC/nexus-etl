"""
Назначение:
    MapperDsl: компиляция MappingSpec в MapperCore.
"""

from __future__ import annotations

from connector.domain.dsl.engine import TransformationEngine
from connector.domain.dsl.build_options import MapDslBuildOptions
from connector.domain.dsl.issues import DslLoadError
from connector.domain.dsl.registry import OperationRegistry
from connector.domain.dsl.specs import MappingSpec, SinkSpec
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
        options: MapDslBuildOptions | None = None,
    ) -> None:
        if engine is None:
            if registry is None:
                engine = TransformationEngine.with_core_ops()
            else:
                engine = TransformationEngine(registry)
        self.engine = engine
        self.options = options or MapDslBuildOptions()

    def compile(self, spec: MappingSpec, *, sink_spec: SinkSpec | None = None) -> MapperCore:
        """
        Назначение:
            Скомпилировать MappingSpec в MapperCore.
        """
        try:
            return MapperCore(spec, self.engine, sink_spec=sink_spec, options=self.options)
        except DslLoadError:
            raise
        except Exception as exc:
            raise DslLoadError(
                code="MAP_DSL_COMPILE_INVALID",
                message=f"Failed to compile mapping DSL: {exc}",
            ) from exc
