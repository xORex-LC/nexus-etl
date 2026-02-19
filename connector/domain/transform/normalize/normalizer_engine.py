"""
Назначение:
    NormalizerEngine: DSL-обвязка стадии normalize (StageEngine).
"""

from __future__ import annotations

from typing import Any

from connector.domain.diagnostics.catalog import ErrorCatalog
from connector.domain.transform.core.result import TransformResult
from connector.domain.dsl.engine import TransformationEngine
from connector.domain.transform_dsl import (
    load_normalize_build_options_for_dataset,
    load_normalize_spec_for_dataset,
    load_sink_spec_for_dataset,
)
from connector.domain.transform_dsl.build_options import NormalizeDslBuildOptions
from connector.domain.transform_dsl.specs import NormalizeSpec, SinkSpec
from connector.domain.transform_dsl.compilers.normalize import NormalizerDsl
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
        sink_spec: SinkSpec | None = None,
        row_builder: RowBuilder | None = None,
        options: NormalizeDslBuildOptions | None = None,
    ) -> None:
        self.catalog = catalog
        self.dsl = dsl or NormalizerDsl(options=options)
        compiled = self.dsl.compile(spec)
        self.core: NormalizerCore = NormalizerCore(
            compiled,
            engine=self.dsl.engine,
            catalog=catalog,
            sink_spec=sink_spec,
            row_builder=row_builder,
        )

    @classmethod
    def from_dataset(
        cls,
        *,
        dataset: str,
        catalog: ErrorCatalog,
        engine: TransformationEngine | None = None,
        row_builder: RowBuilder | None = None,
        options: NormalizeDslBuildOptions | None = None,
    ) -> "NormalizerEngine":
        # NOTE: engine/options overrides are test and migration hooks.
        spec = load_normalize_spec_for_dataset(dataset)
        sink_spec = load_sink_spec_for_dataset(dataset)
        dsl_options = options or load_normalize_build_options_for_dataset(dataset)
        dsl = NormalizerDsl(engine=engine, options=dsl_options)
        return cls(
            spec,
            catalog=catalog,
            dsl=dsl,
            sink_spec=sink_spec,
            row_builder=row_builder,
            options=dsl_options,
        )

    def normalize(self, source: TransformResult[Any]) -> TransformResult[Any]:
        return self.core.normalize(source)
