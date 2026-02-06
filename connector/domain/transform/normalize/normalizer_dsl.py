"""
Назначение:
    NormalizerDsl: компиляция NormalizeSpec в NormalizerCore.
"""

from __future__ import annotations

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.transform.dsl.engine import TransformationEngine
from connector.domain.transform.dsl.registry import OperationRegistry
from connector.domain.transform.dsl.specs import NormalizeSpec
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
    ) -> None:
        if engine is None:
            if registry is None:
                engine = TransformationEngine.with_core_ops()
            else:
                engine = TransformationEngine(registry)
        self.engine = engine

    def compile(
        self,
        spec: NormalizeSpec,
        *,
        catalog: ErrorCatalog,
        row_builder: RowBuilder | None = None,
    ) -> NormalizerCore:
        return NormalizerCore(
            spec,
            engine=self.engine,
            catalog=catalog,
            row_builder=row_builder,
        )
