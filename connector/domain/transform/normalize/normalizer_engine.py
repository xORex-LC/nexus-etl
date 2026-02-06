"""
Назначение:
    NormalizerEngine: DSL-обвязка стадии normalize (StageEngine).
"""

from __future__ import annotations

from typing import Any

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.transform.core.result import TransformResult
from connector.domain.transform.dsl.engine import TransformationEngine
from connector.domain.transform.dsl.loader import load_normalize_spec_for_dataset
from connector.domain.transform.dsl.specs import NormalizeSpec
from connector.domain.transform.normalize.normalizer_dsl import NormalizerDsl
from connector.domain.transform.normalize.normalizer_core import NormalizerCore, RowBuilder


class NormalizerEngine:
    """
    Назначение/ответственность:
        DSL-движок стадии normalize.
    """

    def __init__(
        self,
        spec: NormalizeSpec,
        *,
        catalog: ErrorCatalog,
        dsl: NormalizerDsl | None = None,
        row_builder: RowBuilder | None = None,
    ) -> None:
        self.catalog = catalog
        self.dsl = dsl or NormalizerDsl()
        self.core: NormalizerCore = self.dsl.compile(spec, catalog=catalog, row_builder=row_builder)

    @classmethod
    def from_dataset(
        cls,
        *,
        dataset: str,
        catalog: ErrorCatalog,
        engine: TransformationEngine | None = None,
        row_builder: RowBuilder | None = None,
    ) -> "NormalizerEngine":
        spec = load_normalize_spec_for_dataset(dataset)
        dsl = NormalizerDsl(engine=engine)
        return cls(spec, catalog=catalog, dsl=dsl, row_builder=row_builder)

    def normalize(self, source: TransformResult[Any]) -> TransformResult[Any]:
        return self.core.normalize(source)
