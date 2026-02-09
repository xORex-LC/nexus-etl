"""
Назначение:
    NormalizerDsl: компиляция NormalizeSpec в NormalizerCore.
"""

from __future__ import annotations

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.dsl.build_options import NormalizeDslBuildOptions
from connector.domain.dsl.engine import TransformationEngine
from connector.domain.dsl.registry import OperationRegistry
from connector.domain.dsl.specs import NormalizeSpec, SinkSpec
from connector.domain.transform.normalize.normalizer_core import NormalizerCore, RowBuilder


class NormalizerDsl:
    """
    Назначение/ответственность:
        Преобразует DSL-спеку нормализации в NormalizerCore.
    """

    def __init__(
        self,
        *,
        registry: OperationRegistry | None = None,
        engine: TransformationEngine | None = None,
        options: NormalizeDslBuildOptions | None = None,
    ) -> None:
        if engine is None:
            if registry is None:
                engine = TransformationEngine.with_core_ops()
            else:
                engine = TransformationEngine(registry)
        self.engine = engine
        self.options = options or NormalizeDslBuildOptions()

    def compile(
        self,
        spec: NormalizeSpec,
        *,
        catalog: ErrorCatalog,
        sink_spec: SinkSpec | None = None,
        row_builder: RowBuilder | None = None,
    ) -> NormalizerCore:
        return NormalizerCore(
            spec,
            engine=self.engine,
            catalog=catalog,
            sink_spec=sink_spec,
            row_builder=row_builder,
            options=self.options,
        )
